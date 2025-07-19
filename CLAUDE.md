## Python Best Practices

- Always use typings in python code
- Avoid excessive and/or obvious code comments that just clutter the code
- Use the project logger instead of print statements, use your best judgement about the proper log level to use for each case
- Always clean up unused imports
- Always include stack traces when logging errors in catch blocks
- Avoid swallowing exceptions in most cases.  If you need to catch them for logging, rethrow them
- Don't use relative path imports in python