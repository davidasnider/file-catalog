with open("src/core/config.py", "r") as f:
    content = f.read()

old_code = """    @property
    def vision_display_name(self) -> str:
        return self.vision_model_path.split("/")[-1]

"""
content = content.replace(old_code, "")

with open("src/core/config.py", "w") as f:
    f.write(content)
