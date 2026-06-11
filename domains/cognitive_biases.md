# Cognitive Biases in Decision-Making

## Base Rates

A *base rate* is the underlying frequency of an event in a population, independent of any new evidence. If 1% of a population has a disease, that 1% is the base rate. Base rates are the prior probability before any specific evidence is considered.

## Conditional Probability

Conditional probability — written `P(A | B)` — is the probability of event A given that event B has occurred. A medical test's positive predictive value is `P(disease | positive test)`. Conditional probability is the bridge between base rates and updated beliefs.

## Base Rate Neglect

*Base rate neglect* is the tendency to ignore base-rate information in favor of specific, anecdotal, or representative evidence. The classic example: a doctor told a patient tests positive on a 99%-accurate test for a disease whose base rate is 1 in 10,000 — the doctor overestimates the probability of disease because they neglect the base rate. The actual probability is around 1%, not 99%.

## Representativeness Heuristic

The *representativeness heuristic* is judging the probability of something by how closely it matches a mental prototype. When told "Linda is outspoken, bright, and concerned with social justice," people rate "Linda is a feminist bank teller" as more likely than "Linda is a bank teller" — even though the conjunction must be less probable. This heuristic causes systematic base-rate neglect: matching a prototype feels diagnostic, but ignores how rare the prototype is.

## Anchoring

*Anchoring* is the tendency to rely too heavily on the first piece of information offered — the *anchor* — when making subsequent judgments. Even arbitrary anchors influence estimates. Asked whether Gandhi was older or younger than 35 when he died, then asked to estimate his actual age at death, people anchor on 35 and estimate too low.

## Availability Heuristic

The *availability heuristic* is estimating likelihood by how easily examples come to mind. People rate plane crashes as more likely than they are (vivid, widely reported) and asthma deaths as less likely (mundane, less reported), even though asthma kills many more people. Availability conflates "memorable" with "frequent."

## Bayesian Updating

*Bayesian updating* is the formal procedure for revising a prior probability in light of new evidence. By Bayes' rule:

```
P(H | E) = P(E | H) * P(H) / P(E)
```

Where `P(H)` is the prior (base rate), `P(E | H)` is the likelihood, and `P(H | E)` is the posterior — the updated belief. Bayesian updating is the cure for base-rate neglect: it forces you to multiply the likelihood by the prior rather than treating the likelihood as the answer.
