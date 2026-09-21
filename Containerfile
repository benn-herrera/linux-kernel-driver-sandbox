FROM docker.io/library/debian:trixie-slim

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bc \
    bison \
    build-essential \
    busybox-static \
    ca-certificates \
    cpio \
    dwarves \
    file \
    flex \
    gdb \
    git \
    kmod \
    libelf-dev \
    libncurses-dev \
    libssl-dev \
    lz4 \
    python3 \
    rsync \
    sparse \
    xz-utils \
    zstd \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /kernel
CMD ["bash"]
