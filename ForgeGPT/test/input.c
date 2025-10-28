int f(int x) {
    if (x > 0)
        x = x - 1;
    if (x == 0) return x;
    if (x < 0) if (x == -1) x = 0; // nested if: unchanged for inner
    return x + 1;
}