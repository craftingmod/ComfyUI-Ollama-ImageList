async def comfy_entrypoint():
    from .backend import comfy_entrypoint as load_extension

    return await load_extension()


__all__ = ["comfy_entrypoint"]
