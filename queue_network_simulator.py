from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import itertools
import json
import sys
from math import isclose


def _parse_scalar(text: str):
    text = text.strip()
    if text == "" or text in ("null", "~", "None"):
        return None
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in inner.split(",")]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    in_quotes = None
    for i, ch in enumerate(line):
        if in_quotes:
            if ch == in_quotes:
                in_quotes = None
        elif ch in "\"'":
            in_quotes = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    return lines


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int):
    if index >= len(lines):
        return None, index
    current_indent, _ = lines[index]
    if current_indent < indent:
        return None, index

    if lines[index][1].startswith("- "):
        return _parse_sequence(lines, index, current_indent)
    return _parse_mapping(lines, index, current_indent)


def _parse_sequence(lines: list[tuple[int, str]], index: int, indent: int):
    items = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent != indent or not content.startswith("- "):
            break
        remainder = content[2:].strip()
        if not remainder:
            index += 1
            item, index = _parse_block(lines, index, indent + 2)
            items.append(item)
            continue
        if ":" in remainder and not remainder.startswith(("[", "\"", "'")):
            key, _, value = remainder.partition(":")
            item_lines = [(indent + 2, f"{key.strip()}: {value.strip()}")]
            j = index + 1
            while j < len(lines) and lines[j][0] > indent:
                item_lines.append(lines[j])
                j += 1
            item, _ = _parse_mapping(item_lines, 0, indent + 2)
            items.append(item)
            index = j
            continue
        items.append(_parse_scalar(remainder))
        index += 1
    return items, index


def _parse_mapping(lines: list[tuple[int, str]], index: int, indent: int):
    mapping: dict = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent != indent or content.startswith("- "):
            break
        if ":" not in content:
            raise ValueError(f"Invalid configuration line: {content!r}")
        key, _, value = content.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            mapping[key] = _parse_scalar(value)
            index += 1
        else:
            index += 1
            sub, index = _parse_block(lines, index, indent + 2)
            mapping[key] = sub if sub is not None else {}
    return mapping, index


def load_yaml(text: str) -> dict:
    lines = _prepare_lines(text)
    mapping, _ = _parse_mapping(lines, 0, 0)
    return mapping


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as file:
        content = file.read()
    if path.endswith(".json"):
        return json.loads(content)
    return load_yaml(content)


@dataclass(frozen=True)
class Result:
    id: int
    servers: int
    capacity: int | None
    times: tuple[float, ...]
    probabilities: tuple[float, ...]
    losses: int
    arrivals: int
    completed: int


class LinearCongruentialGenerator:
    def __init__(
        self,
        seed: int = 2026,
        a: int = 1_664_525,
        c: int = 1_013_904_223,
        modulus: int = 2**32,
        limit: int = 100_000,
    ) -> None:
        self.previous = seed
        self.a = a
        self.c = c
        self.modulus = modulus
        self.limit = limit
        self.used = 0

    @property
    def available(self) -> bool:
        return self.used < self.limit

    def next_value(self) -> float:
        if not self.available:
            raise RuntimeError("The pseudo-random number limit has been reached.")
        self.previous = (self.a * self.previous + self.c) % self.modulus
        self.used += 1
        return self.previous / self.modulus


def uniform(generator: LinearCongruentialGenerator, minimum: float, maximum: float) -> float:
    return minimum + (maximum - minimum) * generator.next_value()


@dataclass(frozen=True)
class Route:
    destination: int | None
    probability: float


@dataclass
class Queue:
    id: int
    servers: int
    capacity: int | None
    service_min: float
    service_max: float
    arrival_min: float | None = None
    arrival_max: float | None = None
    first_arrival: float | None = None
    routes: tuple[Route, ...] = ()
    customers: int = field(default=0, init=False)
    losses: int = field(default=0, init=False)
    arrivals: int = field(default=0, init=False)
    completed: int = field(default=0, init=False)
    times: dict[int, float] = field(init=False)

    def __post_init__(self) -> None:
        if self.servers < 1:
            raise ValueError(f"Queue {self.id}: servers must be >= 1.")
        if self.capacity is not None and self.capacity < self.servers:
            raise ValueError(f"Queue {self.id}: capacity must be >= servers.")
        if self.service_min > self.service_max:
            raise ValueError(f"Queue {self.id}: invalid service interval.")
        if (self.arrival_min is None) != (self.arrival_max is None):
            raise ValueError(f"Queue {self.id}: provide both arrival bounds.")
        if (
            self.arrival_min is not None
            and self.arrival_max is not None
            and self.arrival_min > self.arrival_max
        ):
            raise ValueError(f"Queue {self.id}: invalid arrival interval.")
        total = sum(route.probability for route in self.routes)
        if self.routes and not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                f"Queue {self.id}: routing probabilities must sum to 1 "
                f"(current sum: {total})."
            )
        self.times = {}

    def reset(self) -> None:
        self.customers = 0
        self.losses = 0
        self.arrivals = 0
        self.completed = 0
        self.times = {}

    def has_capacity(self) -> bool:
        return self.capacity is None or self.customers < self.capacity


def simulate(
    queues: list[Queue],
    random_limit: int = 100_000,
    seed: int = 2026,
) -> tuple[list[Result], float, int]:
    if not queues:
        raise ValueError("Provide at least one queue.")

    ids = [queue.id for queue in queues]
    if len(set(ids)) != len(ids):
        raise ValueError("Queue ids must be unique.")

    by_id = {queue.id: queue for queue in queues}
    for queue in queues:
        for route in queue.routes:
            if route.destination is not None and route.destination not in by_id:
                raise ValueError(
                    f"Queue {queue.id}: destination {route.destination} does not exist."
                )
        queue.reset()

    generator = LinearCongruentialGenerator(seed=seed, limit=random_limit)
    events: list[tuple[float, int, str, int, int | None]] = []
    counter = itertools.count()
    clock = 0.0
    stop = False

    def schedule(time: float, event_type: str, source: int, destination: int | None = None) -> None:
        heapq.heappush(events, (time, next(counter), event_type, source, destination))

    def accumulate(instant: float) -> None:
        delta = instant - clock
        if delta <= 0:
            return
        for queue in queues:
            queue.times[queue.customers] = queue.times.get(queue.customers, 0.0) + delta

    def choose_destination(queue: Queue) -> int | None:
        nonlocal stop
        if len(queue.routes) <= 1:
            return queue.routes[0].destination if queue.routes else None
        if not generator.available:
            return queue.routes[0].destination
        value = generator.next_value()
        if not generator.available:
            stop = True
        accumulated = 0.0
        for route in queue.routes:
            accumulated += route.probability
            if value <= accumulated:
                return route.destination
        return queue.routes[-1].destination

    def start_service(queue: Queue) -> None:
        nonlocal stop
        duration = uniform(generator, queue.service_min, queue.service_max)
        if not generator.available:
            stop = True
        destination = choose_destination(queue)
        event_type = "TRANSFER" if destination is not None else "DEPARTURE"
        schedule(clock + duration, event_type, queue.id, destination)

    def handle_arrival(queue: Queue) -> None:
        nonlocal stop
        queue.arrivals += 1
        if queue.has_capacity():
            queue.customers += 1
            if queue.customers <= queue.servers and generator.available:
                start_service(queue)
        else:
            queue.losses += 1

        if generator.available:
            assert queue.arrival_min is not None and queue.arrival_max is not None
            interval = uniform(generator, queue.arrival_min, queue.arrival_max)
            schedule(clock + interval, "ARRIVAL", queue.id)
            if not generator.available:
                stop = True

    def handle_departure(queue: Queue) -> None:
        queue.customers -= 1
        queue.completed += 1
        if queue.customers >= queue.servers and generator.available:
            start_service(queue)

    def handle_transfer(source: Queue, destination: Queue) -> None:
        source.customers -= 1
        source.completed += 1
        if source.customers >= source.servers and generator.available:
            start_service(source)

        destination.arrivals += 1
        if destination.has_capacity():
            destination.customers += 1
            if destination.customers <= destination.servers and generator.available:
                start_service(destination)
        else:
            destination.losses += 1

    for queue in queues:
        if queue.arrival_min is not None and queue.first_arrival is not None:
            schedule(queue.first_arrival, "ARRIVAL", queue.id)

    while not stop and events:
        instant, _, event_type, source_id, destination_id = heapq.heappop(events)
        accumulate(instant)
        clock = instant

        if event_type == "ARRIVAL":
            handle_arrival(by_id[source_id])
        elif event_type == "DEPARTURE":
            handle_departure(by_id[source_id])
        else:
            assert destination_id is not None
            handle_transfer(by_id[source_id], by_id[destination_id])

    results = []
    for queue in queues:
        if queue.capacity is not None:
            max_state = queue.capacity
        else:
            max_state = max(queue.times.keys(), default=0)
        times = tuple(queue.times.get(i, 0.0) for i in range(max_state + 1))
        results.append(
            Result(
                id=queue.id,
                servers=queue.servers,
                capacity=queue.capacity,
                times=times,
                probabilities=tuple(time / clock for time in times),
                losses=queue.losses,
                arrivals=queue.arrivals,
                completed=queue.completed,
            )
        )

    assert generator.used == random_limit
    for queue in queues:
        assert isclose(sum(queue.times.values()), clock, rel_tol=0.0, abs_tol=1e-8)
    for result in results:
        assert isclose(sum(result.probabilities), 1.0, rel_tol=0.0, abs_tol=1e-9)

    return results, clock, generator.used


def print_report(results: list[Result], total_time: float, used: int) -> None:
    for result in results:
        capacity = result.capacity if result.capacity is not None else "inf"
        print(f"Queue {result.id} | G/G/{result.servers}/{capacity}")
        print("State | Accumulated time | Probability")
        for state, (time, probability) in enumerate(zip(result.times, result.probabilities)):
            print(f"{state:>5} | {time:>17.6f} | {probability:>11.6%}")
        print(f"Lost customers: {result.losses}")
        print(f"Arrivals processed: {result.arrivals}")
        print(f"Completed services: {result.completed}")
        print()

    print(f"Total simulation time: {total_time:.6f}")
    print(f"Pseudo-random numbers used: {used}")


def queues_from_config(config: dict) -> list[Queue]:
    queues = []
    for item in config["queues"]:
        arrival = item.get("arrival")
        capacity = item.get("capacity")
        if isinstance(capacity, str) and capacity.strip().lower() in (
            "infinite",
            "inf",
        ):
            capacity = None
        queues.append(
            Queue(
                id=item["id"],
                servers=item["servers"],
                capacity=capacity,
                service_min=item["service"][0],
                service_max=item["service"][1],
                arrival_min=arrival[0] if arrival else None,
                arrival_max=arrival[1] if arrival else None,
                first_arrival=item.get("first_arrival"),
                routes=tuple(
                    Route(r["destination"], r["probability"])
                    for r in item.get("routes", [])
                ),
            )
        )
    return queues


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 queue_network_simulator.py config.yml")
        sys.exit(1)

    config = load_config(sys.argv[1])
    queues = queues_from_config(config)
    random_limit = config.get("random_limit", 100_000)
    seed = config.get("seed", 2026)

    results, total_time, used = simulate(queues, random_limit=random_limit, seed=seed)
    print_report(results, total_time, used)


if __name__ == "__main__":
    main()
