# Computers

## Computation and the Turing machine

A computer is a device that mechanically follows a finite set of rules to transform input symbols into output symbols. Turing's model — a head reading and writing on an infinite tape — captures exactly what is computable in principle. Modern hardware is an efficient implementation of this abstraction.

## Algorithms and complexity

An algorithm is a finite procedure that solves a class of problems. The same problem can be solved by many algorithms with vastly different costs. Big-O notation classifies algorithms by how their runtime scales with input size — O(log n), O(n), O(n²), O(2^n).

## Data structures

The choice of how data is laid out in memory determines what operations are cheap. Arrays give fast indexed access; linked lists give fast insertion. Hash tables give amortized O(1) lookup; trees give ordered traversal. Every data structure is a tradeoff.

## Abstraction

The single most important idea in software. Hide implementation details behind an interface so the user can reason about behavior without knowing internals. Languages, operating systems, networks, and the web are nested layers of abstraction.

## State and side effects

A pure function returns the same output for the same input and changes nothing else. State (mutable memory, files, network) makes programs hard to reason about. Functional programming aims to minimize state; imperative programming embraces it. The tradeoff structures most language design.

## Concurrency

Multiple computations making progress at once. Hard because they share state. Race conditions, deadlocks, and partial failures are the difficulty. Channels, locks, actors, and transactional memory are the tools — none of them universal solutions.

## Networks and the internet

Computers exchange messages via layered protocols (link, IP, TCP/UDP, application). The internet is a packet-switched, best-effort network that scaled because no central authority is required for routing. Architecture lessons that recur in every distributed system.

## Programs and proofs

The Curry-Howard correspondence: types are propositions, programs are proofs. A typed program that compiles is a constructive proof that the type's proposition is inhabited. This is why type systems can catch entire classes of bugs at compile time.
