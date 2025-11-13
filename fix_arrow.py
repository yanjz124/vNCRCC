with open('web/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('Dep → Arr', 'Dep-Arr')

with open('web/index.html', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)

print("Fixed arrows")
