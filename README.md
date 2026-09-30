# Simulador de Rede de Filas (T1)

Simulador de eventos discretos para redes de filas G/G/s/c com topologia
arbitrária, carregado a partir de um arquivo de configuração `.yml`.

## Requisitos

- Python 3.10+ (nenhuma biblioteca externa é necessária — o parser de YAML
  usado é implementado no próprio `queue_network_simulator.py`)

## Como executar

```bash
python3 queue_network_simulator.py network_config.yml
```

Isso roda a rede do enunciado (Fila 1 → Fila 2/Fila 3, com realimentação) com
o primeiro cliente chegando em `t=2.0` e encerramento no 100.000º
pseudoaleatório, exatamente como pedido no T1.

## Estrutura do arquivo de configuração (`network_config.yml`)

```yaml
seed: 2026
random_limit: 100000

queues:
  - id: 1
    servers: 1
    capacity: infinite
    arrival: [2.0, 4.0]
    first_arrival: 2.0
    service: [1.0, 2.0]
    routes:
      - destination: 2
        probability: 0.2
      - destination: 3
        probability: 0.8

  - id: 2
    servers: 2
    capacity: 5
    service: [4.0, 6.0]
    routes:
      - destination: 1
        probability: 0.3
      - destination: 3
        probability: 0.5
      - destination: null
        probability: 0.2
```

- `capacity`: número máximo de clientes no sistema (em atendimento + em
  espera). Use `infinite` (ou omita o campo) para uma fila sem limite.
- `arrival`: intervalo de chegadas externas (só para filas que recebem
  clientes de fora da rede).
- `routes`: para onde vai o cliente ao terminar o atendimento; as
  probabilidades de cada fila devem somar 1. `destination: null` representa
  a saída do cliente para fora do sistema. Redes com realimentação (laços,
  como a Fila 2 → Fila 1 do enunciado) são suportadas normalmente.
- `random_limit`: quantidade de pseudoaleatórios usados até a simulação
  encerrar.
- `seed`: semente do gerador congruente linear.

Arquivos `.json` no mesmo formato de chaves também são aceitos.

## Saída

Para cada fila são reportados: o tempo acumulado e a probabilidade de cada
estado (número de clientes no sistema), o total de clientes perdidos (por
falta de capacidade), chegadas processadas e atendimentos concluídos. Ao
final, o tempo global da simulação e o total de pseudoaleatórios usados.

## Resultado de referência (modelo do T1)

O resultado já usado no arquivo de entrega (`T1_SMA.docx`) é a saída direta
de `python3 queue_network_simulator.py network_config.yml` com a
configuração acima.
