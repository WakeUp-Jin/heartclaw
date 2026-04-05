# 天工容器 Dockerfile
#
# 包含：Rust 工具链（预热常用 crate）+ Node.js + Python
# 运行：天工调度器（巡查锻造令 → 调度 Coding Agent CLI）

FROM rust:1.85-slim AS base

# ── 基础工具 ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    pkg-config \
    libssl-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20（Coding Agent CLI 依赖） ─────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Coding Agent CLI（方案 A：仅安装 Codex） ─────
RUN npm install -g @openai/codex \
    && codex --version

# ── 预热 Rust 常用 crate ────────────────────────
# 创建临时项目，添加常用依赖并编译一次。
# 后续锻造新工具时这些 crate 已缓存，编译速度大幅提升。
WORKDIR /tmp/warmup
RUN cargo init --name warmup && \
    cat >> Cargo.toml <<'TOML'

clap = { version = "4", features = ["derive"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
reqwest = { version = "0.12", features = ["json", "blocking"] }
tokio = { version = "1", features = ["full"] }
anyhow = "1"
TOML

RUN cargo build --release 2>&1 \
    && rm -rf src Cargo.toml Cargo.lock
# 保留 target/ 中的编译缓存

# ── Rust 工作空间 ────────────────────────────────
WORKDIR /workspace
RUN cargo init --name tiangong-tool

# ── 天工调度器（Python） ─────────────────────────
WORKDIR /app

# 天工调度器零第三方依赖，只用 Python 标准库

COPY src/tiangong/ /app/tiangong/

# ── 共享卷挂载点 ─────────────────────────────────
VOLUME ["/shared"]

CMD ["python3", "-m", "tiangong.main"]
