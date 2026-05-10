Aqui tens o resumo estruturado de todas as alterações críticas que fizemos para transformar o teu projeto num sistema distribuído a sério. Podes copiar isto diretamente para um ficheiro `REFORMULACAO.md` ou adicionar ao teu `README.md`.

---

# Relatório de Reformulação: Arquitetura P2P Distribuída

Este documento detalha as alterações efetuadas para cumprir os requisitos da disciplina de **Redes e Serviços**, focando-se na eliminação de um servidor centralizado e na implementação de um modelo de rede Mesh descentralizada.

## 1. Mudança de Paradigma: Do Client-Server ao "Servient"

A arquitetura original separava o programa em "Cliente" e "Servidor". Para Redes e Serviços, isto é um ponto de falha único.

* **Alteração:** Cada nó (jogador) passou a ser um **Servient**. Ao iniciar, cada instância levanta o seu próprio servidor gRPC e, simultaneamente, age como cliente para interagir com os outros.
* **Bootstrap:** Eliminou-se a necessidade de um servidor mestre fixo. O primeiro jogador inicia o "mundo" e os seguintes ligam-se a qualquer peer conhecido para entrar na rede.

## 2. Protocolo gRPC e Sincronização de Estado (`game.proto`)

Um problema crítico era a falta de contexto: novos jogadores entravam num mundo vazio.

* **Novo Método `SyncWorld`:** Adicionado ao serviço gRPC. Permite que um novo peer peça a "foto atual" do mundo (posições de todos os jogadores, HP e nomes) ao nó de bootstrap.
* **Serialização JSON:** O estado do jogo é agora convertido para JSON, enviado via gRPC e reconstruído na memória local do novo jogador, garantindo **Consistência de Estado** inicial.

## 3. Gestão de Presença e Resiliência (Heartbeat)

Num sistema P2P, os nós podem falhar sem aviso (crash, queda de rede).

* **Mecanismo de "Touch":** O `network/server.py` agora atualiza um timestamp `last_seen` sempre que recebe qualquer mensagem de um peer.
* **Monitor de Inatividade:** Implementação de uma tarefa assíncrona (`peer_monitor_loop`) no `main.py` que corre em background.
* **Timeout:** Se um jogador não der sinal de vida durante 15 segundos, é removido automaticamente da lista de peers local, garantindo que a rede se auto-limpa de "nós mortos".

## 4. Descoberta de Rede via Kademlia DHT

Utilizámos a Kademlia não apenas como uma base de dados, mas como um serviço de **Peer Discovery**.

* Ao entrar, um nó usa o `FindNode` para descobrir o IP/Porta de outros jogadores na rede através do nó de bootstrap, construindo uma malha (Mesh) onde todos podem falar com todos.

## 5. Contentorização e Portabilidade (Docker)

Para garantir que o projeto corre em qualquer ambiente (e facilitar a correção pelo professor):

* **Dockerization:** Criámos um `Dockerfile` baseado em `python:3.11-slim`.
* **Otimização:** Forçámos a instalação do `setuptools` e `grpcio-tools` para resolver incompatibilidades do gRPC com as versões mais recentes do Python (3.12+).
* **Network Host:** Configurado para permitir que os contentores P2P se descubram facilmente na rede local.

## 6. Resumo Técnico das Funções Implementadas

* `GameState.get_world_state_json()`: Exporta o mundo para novos peers.
* `GameState.apply_world_state()`: Importa o mundo ao entrar.
* `GameState.clean_inactive_peers()`: Remove jogadores que caíram.
* `GameServicer._touch_peer()`: Regista atividade de rede para o heartbeat.

---

### Notas de Execução (via Docker)

1. **Build:** `docker build -t p2p-rpg .`
2. **Nó 1:** `docker run -it --network host p2p-rpg --name Player1 --port 50051`
3. **Nó 2:** `docker run -it --network host p2p-rpg --name Player2 --port 50052 --bootstrap 127.0.0.1:50051`

---

**Estado atual do projeto:** O sistema é agora uma rede P2P pura, resiliente a falhas e com replicação de estado inicial. Cumpre integralmente a sugestão do professor de "depender do 1º player" apenas para o nascimento da rede.