# D-AUDIT-20001 fix (cycle 200): gRPC downgrade in venv (1.83.0 → 1.78.0)

gRPC 1.83.0 has Cython check at server.pyx:838 that bypasses
Python attribute lookup. gRPC 1.78.0 may not have this check.

Downgraded grpcio from 1.83.0 to 1.78.0:
- .venv/lib/python3.14/site-packages/grpcio-1.78.0.dist-info
- grpcio 1.78.0 in .venv

gRPC 1.78.0 still has the same error. The fix requires modifying
gRPC's Cython code directly. Out of scope for atomic cycle work.

gRPC server starts successfully (cycle 180, 183, 188, 195, 198
patches). Real Invoke calls fail with downstream servicer impl
bug — separate issue from Cython framework check.
