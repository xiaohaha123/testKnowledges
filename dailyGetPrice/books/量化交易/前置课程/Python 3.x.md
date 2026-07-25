# 迭代器
把一个类作为一个迭代器使用需要在类中实现两个方法 `__iter__()` 与 `__next__()`
``` python
class MyNumbers:
  def __iter__(self):
    self.a = 1
    return self
 
  def __next__(self):
    if self.a <= 20:
      x = self.a
      self.a += 1
      return x
    else:
      raise StopIteration
 
myclass = MyNumbers()
myiter = iter(myclass)
 
for x in myiter:
  print(x)
```

# 生成器
使用了 yield 的函数被称为生成器（generator），生成器本质是一种特殊、简化的迭代器。

生成器是 Python 提供的语法糖，依靠yield自动生成迭代器，自带上下文保存、send传参能力，代码更简洁。
``` python
import sys
 
def fibonacci(n): # 生成器函数 - 斐波那契
    a, b, counter = 0, 1, 0
    while True:
        if (counter > n): 
            return
        yield a
        a, b = b, a + b
        counter += 1
f = fibonacci(10) # f 是一个迭代器，由生成器返回生成
 
while True:
    try:
        print (next(f), end=" ")
    except StopIteration:
        sys.exit()
```

# with关键字
with 是 Python 中的一个关键字，用于上下文管理协议（Context Management Protocol）。它简化了资源管理代码，特别是那些需要明确释放或清理的资源（如文件、网络连接、数据库连接等）

**with 语句的优势**：with 语句通过上下文管理协议（Context Management Protocol）解决了这些问题：
+ 自动资源释放：确保资源在使用后被正确关闭
+ 代码简洁：减少样板代码
+ 异常安全：即使在代码块中发生异常，资源也会被正确释放
+ 可读性强：明确标识资源的作用域
``` python
with open('example.txt', 'r') as file:
    content = file.read()
    print(content)
# 文件已自动关闭
```

# 函数
加了星号 * 的参数会以元组(tuple)。如果单独出现星号 *，则星号 * 后的参数必须用关键字传入。
加了两个星号 ** 的参数会以字典的形式导入
``` python
# 可写函数说明
def printinfo( arg1, **vardict ):
   "打印任何传入的参数"
   print ("输出: ")
   print (arg1)
   print (vardict)
 
# 调用printinfo 函数
printinfo(1, a=2,b=3)
```

lambada匿名函数：
``` python
from functools import reduce
 
numbers = [1, 2, 3, 4, 5]
# 使用 reduce() 和 lambda 函数计算乘积
product = reduce(lambda x, y: x * y, numbers)
print(product)  # 输出：120
```

# 装饰器
装饰器（decorator）是 Python 中的一种高级功能，用于在不修改原函数代码的前提下，动态扩展函数或类的功能。

本质上，装饰器是一个函数：它接收一个函数作为参数，并返回一个新的函数（通常是对原函数的增强版本）
``` python
def my_decorator(func):
    def wrapper(*args, **kwargs):
        print("执行前")
        res = func(*args, **kwargs)
        print("执行后")
        return res
    return wrapper

@my_decorator
def greet(name):
    print(f"Hello, {name}!")

greet("Alice")
```

# 异常捕获
异常捕捉可以使用 try/except 语句
``` python
def divide(x, y):
    try:
        result = x / y
    except ZeroDivisionError:
        print("division by zero!")
    else:
        print("result is", result)
    finally:
        print("executing finally clause")
```

# 虚拟环境
``` python
# 基本语法
python3 -m venv 环境名称

# 激活环境：Linux
source .venv/bin/
# 激活环境：Windows
.venv\Scripts\activate

# pip install -i https://pypi.tuna.tsinghua.edu.cn/simple package_name

# 退出虚拟环境
deactivate
```