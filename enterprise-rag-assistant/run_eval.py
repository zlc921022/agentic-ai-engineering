"""Ragas 评估入口。"""

from runpy import run_module


if __name__ == "__main__":
    run_module("src.evaluator", run_name="__main__")
