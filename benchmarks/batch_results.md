# Batch simulation results

Measured with:

```text
python benchmarks/measure_batch_engine.py
```

The harness runs each batch size in a fresh process, performs one warm-up and
five measured repetitions, and reports the median. Every sample includes
seeded setup, all turns under the same legal pseudo-random bid policy,
first-card reveals, terminal scoring, and ranking. Peak RSS is the process
high-water mark reported by the operating system.

Results on the development machine:

| Batch size | Median seconds | Games/second | Peak RSS |
| ---: | ---: | ---: | ---: |
| 1 | 0.021417 | 46.69 | 45.0 MiB |
| 64 | 0.030627 | 2,089.66 | 45.5 MiB |
| 256 | 0.043982 | 5,820.59 | 48.1 MiB |
| 1,024 | 0.095019 | 10,776.79 | 56.8 MiB |
| 4,096 | 0.294088 | 13,927.82 | 91.4 MiB |

Batch size one exposes NumPy's fixed setup and dispatch overhead. The intended
RL path advances hundreds or thousands of games per call; at 1,024 games the
engine is about 19 times faster than the downstream retired scalar engine's
554.68 games/second baseline.
