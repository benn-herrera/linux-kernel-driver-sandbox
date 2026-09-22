FROM docker.io/library/debian:trixie-slim

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bc \
    bindgen \
    bison \
    build-essential \
    busybox-static \
    ca-certificates \
    clang \
    cpio \
    curl \
    dwarves \
    file \
    flex \
    gdb \
    git \
    just \
    kmod \
    libelf-dev \
    libncurses-dev \
    libssl-dev \
    lld \
    llvm \
    lz4 \
    python3 \
    rsync \
    rust-clippy \
    rust-src \
    rustc \
    rustfmt \
    sparse \
    xz-utils \
    zstd \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /kernel
CMD ["bash"]
