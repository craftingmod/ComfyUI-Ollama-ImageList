async def comfy_entrypoint():
    from .extension import comfy_entrypoint as load_extension

    return await load_extension()


__all__ = ["comfy_entrypoint"]
