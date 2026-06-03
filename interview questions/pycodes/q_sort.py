def test(arr):
    if len(arr) <= 1:
        return arr
    mid = arr[0]
    left = [x for x in arr[1:] if x < mid]
    right = [x for x in arr[1:] if x >= mid]
    return test(left) + [mid] + test(right)

if __name__ == "__main__":
    arr = [3, 6, 8, 10, 1, 2, 1]
    print(test(arr))