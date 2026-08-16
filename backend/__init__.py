PROJECT_ID = "ollama-image-list"
PROJECT_NAME = "Ollama-ImageList"


async def comfy_entrypoint():
    from .extension import comfy_entrypoint as load_extension

    return await load_extension()


__all__ = ["PROJECT_ID", "PROJECT_NAME", "comfy_entrypoint"]
