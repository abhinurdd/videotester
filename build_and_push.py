import subprocess
import sys
import os

def execute_command(command: str):
    """Run a shell command and stream its output."""
    print(f"\n🚀 Running: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"✅ Command succeeded: {command}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing: {command}")
        sys.exit(e.returncode)

def main():
    if len(sys.argv) < 2:
        print("Usage: python build_and_push.py [dev|prod]")
        sys.exit(1)

    target = sys.argv[1].strip().lower()

    docker_user = "technurdd"
    image_name = "content-analysis"
    dockerfile = "Dockerfile"
    context = "."
    
    tag_remote = f"{docker_user}/{image_name}:{target}"

    if target not in {"dev", "prod"}:
        print("Unknown target. Use: dev or prod")
        sys.exit(1)



    # Build specifically for ARM-based CPUs (EC2 t4g.micro)
    platform_arg = "--platform linux/arm64 "
    
    # Simple caching
    cache_arg = "--cache-to type=inline "

    print(f"🛠️ Starting build for: {tag_remote} (Target: {target})")

    build_cmd = (
        f"docker buildx build "
        f"{platform_arg}"
        f"-t {tag_remote} "
        f"-f {dockerfile} "
        f"{cache_arg}"
        f"--push "
        f"{context}"
    )

    execute_command(build_cmd)
    
    print(f"\n✨ Successfully built and pushed {tag_remote} to Docker Hub!")
    print(f"📝 On your EC2, you can now run: docker-compose up -d")

if __name__ == "__main__":
    main()
