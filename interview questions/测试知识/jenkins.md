# 一、Jenkins 是什么？

> **Jenkins 是一个开源的持续集成 / 持续交付（CI/CD）工具，用来自动化构建、测试、部署代码。**

- 基于 Java

- 插件生态丰富

- 支持 Pipeline as Code

- 常用于接口自动化 / UI 自动化 / 发布流水线

---

# 二、Jenkins 中 Freestyle 和 Pipeline 的区别？

| 对比项  | Freestyle | Pipeline        |
| ---- | --------- | --------------- |
| 配置方式 | 页面勾选      | Groovy 脚本       |
| 可维护性 | 差         | ✅ 好             |
| 复杂逻辑 | 不支持       | ✅ 支持            |
| 版本控制 | ❌         | ✅ (Jenkinsfile) |
| 推荐使用 | 简单任务      | ✅ 正式项目          |

✅ **面试必答：**

> Freestyle 适合简单任务，Pipeline 适合复杂 CI/CD 流程，我项目中一般用 Declarative Pipeline 写成 Jenkinsfile 纳入 Git 管理。

---

# 三、什么是 Jenkins Pipeline？有哪两种？

### ✅ 两种 Pipeline

| 类型                        | 说明             |
| ------------------------- | -------------- |
| Declarative Pipeline（推荐）​ | 结构清晰，易读        |
| Scripted Pipeline         | 旧式，Groovy 自由写法 |

### ✅ 示例（Declarative）

```
pipeline {
    agent any

    stages {
        stage('拉代码') {
            steps {
                git 'https://github.com/xxx.git'
            }
        }
        stage('运行测试') {
            steps {
                sh 'pytest tests/'
            }
        }
    }

    post {
        failure {
            echo '测试失败'
        }
    }
}
```

---

# 四、Jenkins 触发构建方式有哪几种？

✅ 常见触发方式：

1. **手动触发（Build Now）**

2. **定时构建（Poll SCM / cron）**
   
   ```
   H 2 * * *
   ```

3. **Git Webhook（Push / MR）**

4. **上游 Job 触发（Build after other projects）**

✅ 面试答：

> 我一般用 Git Webhook 触发自动化测试 Job，定时任务做每日回归。

---

# 五、Jenkins 如何传参？

### ✅ 勾选 **This project is parameterized**

- String Parameter

- Choice Parameter

- Boolean Parameter

Pipeline 中：

```
parameters {
    string(name: 'ENV', defaultValue: 'test', description: '环境')
}

stage('测试') {
    steps {
        sh "pytest -m ${params.ENV}"
    }
}
```

---

# 六、Jenkins 邮件 / 告警怎么做？

- 安装 **Email Extension Plugin**

- 配置 SMTP

- 在 `post`中：

```
post {
    failure {
        mail to: 'qa@company.com',
             subject: "构建失败",
             body: "${BUILD_URL}"
    }
}
```

✅ 实际项目也可用钉钉 / 企业微信机器人

---

# 七、Jenkins 权限怎么控制？

✅ 使用 **Role-based Authorization Strategy 插件**

- 创建角色（Developer / QA / Admin）

- 绑定：
  
  - Job 权限
  
  - 查看权限
  
  - 构建 / 配置权限

✅ 面试答：

> 通过 RBAC 插件控制权限，不同角色只能看/构建对应 Job，避免误操作。

---

# 八、Jenkins Slave / Agent 是什么？

> **Slave（节点）是执行构建任务的机器，Master 负责任务调度。**

```
pipeline {
    agent { label 'python-node' }
    stages { ... }
}
```

✅ 好处：

- 分散负载

- 不同环境（Linux / Windows / Mac）

---

# 九、Jenkins 构建失败如何排查？

排查步骤：

1. 查看 **Console Output**

2. 确认：
   
   - 代码是否拉取成功
   
   - 依赖是否安装
   
   - 环境变量是否正确

3. 检查：
   
   - 节点是否在线
   
   - 权限问题

4. 本地复现命令

✅ 面试答：

> 首先看 Console Log，定位是哪一步失败，然后在对应 Slave 上手动执行命令复现，确认是环境、依赖还是脚本问题。

---

# 十、Jenkinsfile 为什么要放进 Git？

✅ 原因：

- 版本可追溯

- 多人协作

- 回滚方便

- 符合 IaC 思想

> Pipeline as Code 是 Jenkins 最佳实践。

---

# 十一、面试万能总结回答

> **我在项目中使用 Jenkins 搭建接口自动化 / 发布流水线，通过 Git Webhook 触发，Pipeline 写成 Jenkinsfile 纳入版本控制，配合定时任务和失败告警，保证测试及时执行和问题快速反馈。**

---

# 十二、一句话总结

> **Jenkins = 自动化引擎，Pipeline = 灵魂，Jenkinsfile = 工程化。**
