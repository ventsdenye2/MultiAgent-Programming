from merge import merge_layers


def build_config(defaults, overrides, environ):
    return merge_layers(defaults, overrides)
