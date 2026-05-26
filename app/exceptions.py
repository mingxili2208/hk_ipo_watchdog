"""自定义异常类型。"""


class ConfigError(Exception):
    """配置错误。"""


class FetchError(Exception):
    """网络请求错误。"""


class ParseError(Exception):
    """解析错误。"""


class StrategyError(Exception):
    """策略引擎错误。"""


class LLMError(Exception):
    """LLM 调用错误。"""


class NotificationError(Exception):
    """推送发送错误。"""


class RepositoryError(Exception):
    """数据存储错误。"""
