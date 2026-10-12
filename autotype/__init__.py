import os

# Must run before NumPy loads. Its bundled BLAS wakes worker threads for every
# small template product, which costs milliseconds per letter instead of
# microseconds and starves the capture loop.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_name, "1")
