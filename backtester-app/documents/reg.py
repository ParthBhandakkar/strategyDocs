def factorial(n: int) -> int:
    if n < 0:
        return -1 # Undefined for negative numbers
    if n == 0 or n == 1:
        return 1
    return n * factorial(n - 1)

print(factorial(5)) # Should return 120)