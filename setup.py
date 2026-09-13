"""Setup script for the Nexino PrintFlow Print Agent package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the long description from README if it exists
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="nexino-printflow-agent",
    version="1.0.0",
    author="Nexino PrintFlow",
    author_email="support@nexino.com",
    description="Print agent for Nexino PrintFlow - manages authorized print jobs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nexino/printflow-agent",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.31.0",
        "websocket-client>=1.6.0",
        "python-dotenv>=1.0.0",
        "watchdog>=3.0.0",
        "psutil>=5.9.0",
        "Pillow>=10.0.0",
    ],
    extras_require={
        "windows": [
            "pywin32>=306",
        ],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "nexino-agent=nexino_agent.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Printing",
        "Typing :: Typed",
    ],
    package_data={
        "": ["*.env", "*.md"],
    },
    include_package_data=True,
)
