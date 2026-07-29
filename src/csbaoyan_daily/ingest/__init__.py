"""本地 NTQQ 数据库直读导出器（路线 B）。

读取本机已解密的 NTQQ 明文 SQLite 数据库，按目标群 + 日期抽取消息，
映射成项目现有的 QCE JSON schema，供下游 `generate` / `pipeline` 无差别消费。

不创建任何 QQ 登录会话，纯本地文件操作，规避协议层封号风险。
"""
