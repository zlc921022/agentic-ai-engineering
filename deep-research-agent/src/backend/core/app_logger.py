import logging
from pathlib import Path


LOG_FILE_NAME = "app.log"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(name: str = "deep-research-agent") -> logging.Logger:
    """获取项目统一 logger。

    这个函数会同时配置控制台输出和文件输出，后续重复调用同名 logger
    时直接复用已有 handler，避免日志被重复打印。
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_dir = Path(__file__).resolve().parents[3] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    # 控制台日志：方便开发时直接观察当前执行阶段。
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # 文件日志：保留完整异常栈，方便排查前端页面不直接展示的错误。
    file_handler = logging.FileHandler(log_dir / LOG_FILE_NAME, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
