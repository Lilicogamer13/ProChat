# ProChat
ProChat (Proxy Chat) is a chat system that uses connected clients as relays for other clients, allowing the server to run on very low-power or inexpensive hardware. The codebase is fully documented.

# How It Works
1. The server pairs the first two connected clients directly:

   * Client 1 is linked to Client 2.
   * Client 1 also stays linked to the server.

2. When a third client joins, it asks the server which client it should use as a proxy.
   The server performs a latency-based selection:
     * It compares the direct delay between Client 3 and each available proxy candidate (Client X).
     * If there is a tie, it compares the delay from Client X to the server.
     * If still tied, it compares the combined path Client 3 → Client X → server.
     * If all metrics tie, its picked randomly.

3. This process repeats for each new client:
   * Client 4 is evaluated against Clients 1–3.
   * Client 5 is evaluated against Clients 1–4.
   * And so on.

This ensures that every new client selects the most efficient proxy path available.
