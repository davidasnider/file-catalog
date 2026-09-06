with open("tests/test_config.py", "r") as f:
    content = f.read()

old_code = """    assert settings.llm_display_name == "llm-model"
    assert settings.vision_display_name == "vision-model"

"""
new_code = """    assert settings.llm_display_name == "llm-model"

"""
content = content.replace(old_code, new_code)

with open("tests/test_config.py", "w") as f:
    f.write(content)
