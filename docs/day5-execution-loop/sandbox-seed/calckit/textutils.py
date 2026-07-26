def slugify(text):
    # Seeded gap: does not lowercase, so "Hello World" -> "Hello-World".
    return "-".join(text.split())
