import re

def load_questions(filepath: str) -> list[dict]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'─+', content)
    questions = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = [l.strip() for l in block.split('\n') if l.strip()]
        question_text = None
        options = {}
        correct_letter = None

        for line in lines:
            m = re.match(r'❓\s*\d+\.\s*(.+)', line)
            if m:
                question_text = m.group(1).strip()
                continue

            m = re.match(r'([A-D])\)\s*(.+)', line)
            if m:
                options[m.group(1)] = m.group(2).strip()
                continue

            m = re.search(r"To'g'ri javob:\s*([A-D])", line)
            if m:
                correct_letter = m.group(1)

        if question_text and len(options) == 4 and correct_letter:
            opts_list = [options[l] for l in 'ABCD']
            correct_idx = 'ABCD'.index(correct_letter)
            questions.append({
                'question': question_text[:300],
                'options': [o[:100] for o in opts_list],
                'correct_id': correct_idx
            })

    return questions


if __name__ == '__main__':
    qs = load_questions('questions.txt')
    print(f"Jami {len(qs)} ta savol yuklandi.")
    print("Namuna:", qs[0]['question'])
