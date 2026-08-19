from setuptools import setup, find_packages

setup(
    name="my_bot_platform",
    version="0.1.0",
    packages=find_packages(include=["shared_lib", "shared_lib.*"]),
    install_requires=[
        "reflex",
        "discord.py",
        "sqlalchemy",
    ],
)