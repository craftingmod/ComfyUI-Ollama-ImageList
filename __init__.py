async def comfy_entrypoint():
    from .backend import comfy_entrypoint as load_extension

    return await load_extension()


WEB_DIRECTORY = "./dist"


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
