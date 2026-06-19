# Sample Results

Measured on this workspace with:

```text
py benchmarks\measure_runtime.py
```

Current output:

```text
scenario: players=3 turns=5 bytes=92
decode: iterations=200 avg_ms=0.0786 p95_ms=0.1621
decode_and_reconstruct: iterations=200 avg_ms=0.1504 p95_ms=0.2961
scenario: players=3 turns=10 bytes=137
decode: iterations=200 avg_ms=0.1235 p95_ms=0.2148
decode_and_reconstruct: iterations=200 avg_ms=0.2596 p95_ms=0.4370
scenario: players=3 turns=20 bytes=228
decode: iterations=200 avg_ms=0.2074 p95_ms=0.4175
decode_and_reconstruct: iterations=200 avg_ms=0.3758 p95_ms=0.5878
scenario: players=4 turns=5 bytes=97
decode: iterations=200 avg_ms=0.0985 p95_ms=0.2113
decode_and_reconstruct: iterations=200 avg_ms=0.1668 p95_ms=0.3038
scenario: players=4 turns=10 bytes=147
decode: iterations=200 avg_ms=0.1615 p95_ms=0.2575
decode_and_reconstruct: iterations=200 avg_ms=0.3029 p95_ms=0.4344
scenario: players=4 turns=20 bytes=248
decode: iterations=200 avg_ms=0.2493 p95_ms=0.4262
decode_and_reconstruct: iterations=200 avg_ms=0.4894 p95_ms=0.7949
scenario: players=5 turns=5 bytes=102
decode: iterations=200 avg_ms=0.0885 p95_ms=0.1884
decode_and_reconstruct: iterations=200 avg_ms=0.2058 p95_ms=0.3363
scenario: players=5 turns=10 bytes=157
decode: iterations=200 avg_ms=0.1473 p95_ms=0.2338
decode_and_reconstruct: iterations=200 avg_ms=0.2762 p95_ms=0.5519
scenario: players=5 turns=20 bytes=268
decode: iterations=200 avg_ms=0.3033 p95_ms=0.5085
decode_and_reconstruct: iterations=200 avg_ms=0.5165 p95_ms=0.8366
parallel_callback_batch_32: iterations=50 avg_ms=0.2599 p95_ms=0.4582
```
