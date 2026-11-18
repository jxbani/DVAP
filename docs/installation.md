# Installation

Install Docker for your OS, get DVAP, then run `./dvap doctor` and `./dvap up`. Doctor tells you
exactly what to fix if anything is missing. Hardware per LLM mode: [Requirements](requirements.md).

=== "Linux"

    1. Install **Docker Engine and the Compose plugin** from Docker's own repository (distribution
       packages are often too old): https://docs.docker.com/engine/install/
    2. Let your user run Docker without `sudo`, then **log out and back in**:
       ```bash
       sudo usermod -aG docker $USER
       ```
    3. Get DVAP and start it:
       ```bash
       git clone https://github.com/jxbani/DVAP.git && cd DVAP
       ./dvap doctor
       ./dvap up
       ```

    Works on x86_64 and arm64 (including a Raspberry Pi 4/5 with a 64-bit OS, in `replay` or `api`
    mode). With an NVIDIA GPU, `ollama` mode can use it: uncomment the `deploy:` block of the
    `ollama` service in `docker-compose.yml` (needs the NVIDIA Container Toolkit).

=== "macOS (Apple Silicon or Intel)"

    1. Install **Docker Desktop**: https://docs.docker.com/desktop/setup/install/mac-install/ and start it.
    2. For `ollama` mode, give Docker at least 8 GB: **Settings → Resources → Memory**, then
       **Apply & restart**. (`replay` and `api` need 4 GB, the default is usually enough.)
    3. Get DVAP and start it (macOS has `git` and Python 3 once the Xcode command-line tools are
       installed; it offers to install them the first time you run `git`):
       ```bash
       git clone https://github.com/jxbani/DVAP.git && cd DVAP
       ./dvap doctor
       ./dvap up
       ```

    The images are native arm64 and amd64, so Apple Silicon needs no Rosetta emulation. Docker on
    macOS can't use the GPU, so in `ollama` mode the model runs on the CPU: expect slow decisions.

=== "Windows (WSL2, recommended)"

    1. Install WSL2 and a Linux distribution (Ubuntu is fine), in PowerShell as administrator:
       ```powershell
       wsl --install
       ```
    2. Install **Docker Desktop**: https://docs.docker.com/desktop/setup/install/windows-install/,
       keep the **WSL2 backend**, and turn on your distro under **Settings → Resources → WSL integration**.
    3. For `ollama` mode, give WSL at least 8 GB: create `%UserProfile%\.wslconfig` with
       ```ini
       [wsl2]
       memory=8GB
       ```
       then run `wsl --shutdown` and restart Docker Desktop.
    4. In the **WSL shell**, clone into your Linux home directory (not `/mnt/c/...`, which is much
       slower) and start DVAP:
       ```bash
       cd ~ && git clone https://github.com/jxbani/DVAP.git && cd DVAP
       ./dvap doctor
       ./dvap up
       ```

    Open the lab's URLs (http://127.0.0.1:8090 and so on) in your Windows browser as usual.

=== "Windows (PowerShell, without WSL)"

    1. Install **Docker Desktop** (WSL2 backend) and Python 3 (from python.org, or `winget install Python.Python.3.12`).
    2. Get DVAP, either `git clone https://github.com/jxbani/DVAP.git` or the release zip, then in
       PowerShell in that folder:
       ```powershell
       .\dvap.ps1 doctor
       .\dvap.ps1 up
       ```
    3. If PowerShell refuses to run the script, allow local scripts for your user once:
       `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

    Line endings are handled by `.gitattributes`, so a Windows checkout works. `make` targets need a
    Unix shell; use the `.\dvap.ps1` commands instead.

## Without cloning: the release zip

Every [release](https://github.com/jxbani/DVAP/releases/latest) has a `dvap-<version>.zip` with just
what's needed to run the lab from the published images: `docker-compose.yml`, `.env.example`, the
`dvap` CLI and the challenge files. Unzip it, `cd` into the folder, and run `./dvap up`. To upgrade,
download the new zip and copy your `.env` into it. (`./dvap up --build` and `./dvap update` need a
git clone.)

## Verifying the images

The images on ghcr.io are signed with cosign and carry build-provenance attestations; each release
also lists an SBOM per image. How to verify them: [Releasing → Verifying a release](RELEASING.md#verifying-a-release-anyone).

## Uninstalling

```bash
./dvap down                                  # stop; keeps data and the model
docker compose down -v --rmi all             # remove the lab's containers, volumes (incl. the model) and images
```

Then delete the folder.
