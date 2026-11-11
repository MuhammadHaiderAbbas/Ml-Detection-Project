# CSE-CIC-IDS2018: static vs adaptive models over time

Provenance: **controlled_experiment**. Run started 2026-10-12T04:11:10+00:00. Public dataset; labels are the dataset's own, not analyst-confirmed.

Model: RandomForestClassifier(n_estimators=100), binary attack vs benign, seed 0. Per day, up to 60,000 benign rows and 20,000 rows per attack class were sampled (seeded). Training sets are capped at 400,000 rows. Tuesday 20-02-2018 (4 GB; the only processed file with IP and flow-ID columns) is not included in this study.

## Data

| Day | Rows in file | Header rows | Infinite | Kept | Sampled | Labels in sample |
|---|---|---|---|---|---|---|
| 2018-02-14 | 1,048,575 | 0 | 3,824 | 1,044,746 | 100,000 | Benign 60,000, SSH-Bruteforce 20,000, FTP-BruteForce 20,000 |
| 2018-02-15 | 1,048,575 | 0 | 8,027 | 1,040,548 | 90,990 | Benign 60,000, DoS attacks-GoldenEye 20,000, DoS attacks-Slowloris 10,990 |
| 2018-02-16 | 1,048,575 | 1 | 0 | 1,048,574 | 100,000 | Benign 60,000, DoS attacks-Hulk 20,000, DoS attacks-SlowHTTPTest 20,000 |
| 2018-02-21 | 1,048,575 | 0 | 0 | 1,048,575 | 81,730 | Benign 60,000, DDOS attack-HOIC 20,000, DDOS attack-LOIC-UDP 1,730 |
| 2018-02-22 | 1,048,575 | 0 | 5,610 | 1,042,956 | 60,362 | Benign 60,000, Brute Force -Web 249, Brute Force -XSS 79, SQL Injection 34 |
| 2018-02-23 | 1,048,575 | 0 | 5,708 | 1,042,867 | 60,566 | Benign 60,000, Brute Force -Web 362, Brute Force -XSS 151, SQL Injection 53 |
| 2018-02-28 | 613,104 | 33 | 6,169 | 606,902 | 80,000 | Benign 60,000, Infilteration 20,000 |
| 2018-03-01 | 331,125 | 25 | 2,919 | 328,181 | 80,000 | Benign 60,000, Infilteration 20,000 |
| 2018-03-02 | 1,048,575 | 0 | 4,050 | 1,044,525 | 80,000 | Benign 60,000, Bot 20,000 |

## Results per test day (attack vs benign)

| Day | Novel attack types | Static recall / FPR | Retrain-always recall / FPR | Governed recall / FPR | Governed model trained through |
|---|---|---|---|---|---|
| 2018-02-15 | DoS attacks-GoldenEye, DoS attacks-Slowloris | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 2018-02-14 |
| 2018-02-16 | DoS attacks-Hulk, DoS attacks-SlowHTTPTest | 50.0 % / 0.0 % | 99.5 % / 0.2 % | 99.5 % / 0.0 % | 2018-02-15 |
| 2018-02-21 | DDOS attack-HOIC, DDOS attack-LOIC-UDP | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 2018-02-16 |
| 2018-02-22 | Brute Force -Web, Brute Force -XSS, SQL Injection | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 0.0 % / 0.0 % | 2018-02-21 |
| 2018-02-23 | — | 0.2 % / 0.0 % | 60.8 % / 0.0 % | 56.0 % / 0.0 % | 2018-02-22 |
| 2018-02-28 | Infilteration | 0.0 % / 0.0 % | 0.1 % / 0.1 % | 0.1 % / 0.1 % | 2018-02-23 |
| 2018-03-01 | — | 0.1 % / 0.0 % | 10.5 % / 7.8 % | 0.1 % / 0.1 % | 2018-02-23 |
| 2018-03-02 | Bot | 0.0 % / 0.0 % | 4.7 % / 1.6 % | 0.0 % / 0.0 % | 2018-02-23 |

## Paired differences against the static model (95 % bootstrap CI)

| Day | Retrain-always: recall | Retrain-always: FPR | Governed: recall | Governed: FPR |
|---|---|---|---|---|
| 2018-02-15 | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] |
| 2018-02-16 | +49.5 pp [+49.0, +50.0] | +0.2 pp [+0.2, +0.3] | +49.5 pp [+49.0, +50.0] | +0.0 pp [+0.0, +0.0] |
| 2018-02-21 | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] |
| 2018-02-22 | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] |
| 2018-02-23 | +60.6 pp [+56.6, +64.3] | +0.0 pp [+0.0, +0.0] | +55.8 pp [+51.5, +59.7] | +0.0 pp [+0.0, +0.0] |
| 2018-02-28 | +0.1 pp [+0.0, +0.1] | +0.1 pp [+0.1, +0.1] | +0.1 pp [+0.0, +0.1] | +0.1 pp [+0.1, +0.1] |
| 2018-03-01 | +10.4 pp [+10.1, +10.9] | +7.7 pp [+7.5, +7.9] | -0.0 pp [-0.1, +0.0] | +0.1 pp [+0.0, +0.1] |
| 2018-03-02 | +4.7 pp [+4.4, +5.0] | +1.6 pp [+1.5, +1.7] | +0.0 pp [+0.0, +0.0] | +0.0 pp [+0.0, +0.0] |

## Recall by attack type

| Day | Attack type | Events | Seen before | Static | Retrain-always | Governed |
|---|---|---|---|---|---|---|
| 2018-02-15 | DoS attacks-GoldenEye | 20,000 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-15 | DoS attacks-Slowloris | 10,990 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-16 | DoS attacks-Hulk | 20,000 | no | 0.0 % | 99.0 % | 99.0 % |
| 2018-02-16 | DoS attacks-SlowHTTPTest | 20,000 | no | 100.0 % | 100.0 % | 100.0 % |
| 2018-02-21 | DDOS attack-HOIC | 20,000 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-21 | DDOS attack-LOIC-UDP | 1,730 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-22 | Brute Force -Web | 249 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-22 | Brute Force -XSS | 79 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-22 | SQL Injection | 34 | no | 0.0 % | 0.0 % | 0.0 % |
| 2018-02-23 | Brute Force -Web | 362 | yes | 0.3 % | 47.5 % | 43.6 % |
| 2018-02-23 | Brute Force -XSS | 151 | yes | 0.0 % | 89.4 % | 83.4 % |
| 2018-02-23 | SQL Injection | 53 | yes | 0.0 % | 69.8 % | 62.3 % |
| 2018-02-28 | Infilteration | 20,000 | no | 0.0 % | 0.1 % | 0.1 % |
| 2018-03-01 | Infilteration | 20,000 | yes | 0.1 % | 10.5 % | 0.1 % |
| 2018-03-02 | Bot | 20,000 | no | 0.0 % | 4.7 % | 0.0 % |

## Governance decisions

| After labels of | Verdict | Failed gates | Promoted |
|---|---|---|---|
| 2018-02-15 | pass | — | yes |
| 2018-02-16 | pass | — | yes |
| 2018-02-21 | pass | — | yes |
| 2018-02-22 | pass | — | yes |
| 2018-02-23 | pass | — | yes |
| 2018-02-28 | fail | non_inferior_false_positive_rate | no |
| 2018-03-01 | fail | non_inferior_false_positive_rate | no |
| 2018-03-02 | fail | non_inferior_false_positive_rate | no |

## Drift

| Day | Benign features with major / moderate drift (of all) | Top PSI | ADWIN alarms on static errors | First alarm (events into the day) |
|---|---|---|---|---|
| 2018-02-15 | 0 / 0 (of 78) | Fwd IAT Max 0.048, Flow IAT Min 0.04, Bwd IAT Min 0.039 | 53 | 32703 |
| 2018-02-16 | 64 / 2 (of 78) | Fwd Seg Size Min 11.086, Init Fwd Win Byts 9.311, Fwd Pkt Len Max 9.116 | 147 | 113 |
| 2018-02-21 | 65 / 2 (of 78) | Init Fwd Win Byts 9.135, Fwd Pkt Len Max 9.05, Tot Fwd Pkts 8.511 | 0 | — |
| 2018-02-22 | 0 / 2 (of 78) | Bwd Pkt Len Max 0.144, Pkt Len Max 0.139, Init Fwd Win Byts 0.076 | 0 | — |
| 2018-02-23 | 0 / 3 (of 78) | Bwd Pkt Len Max 0.198, Pkt Len Max 0.197, Fwd Pkt Len Max 0.109 | 0 | — |
| 2018-02-28 | 3 / 18 (of 78) | Dst Port 0.356, Fwd Seg Size Min 0.324, Flow IAT Min 0.309 | 0 | — |
| 2018-03-01 | 3 / 15 (of 78) | Bwd Pkt Len Mean 0.276, Bwd Seg Size Avg 0.276, Dst Port 0.267 | 0 | — |
| 2018-03-02 | 2 / 2 (of 78) | Bwd Pkt Len Mean 0.427, Bwd Seg Size Avg 0.427, RST Flag Cnt 0.14 | 0 | — |

Runtime: 802.9 s in total; peak memory 4,818.1 MB.
