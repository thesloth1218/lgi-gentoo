#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
BUNDLE="$ROOT/.lgi-ansible"

python3 -m venv "$BUNDLE"
"$BUNDLE/bin/python" -m pip install --upgrade pip
"$BUNDLE/bin/python" -m pip install ansible-core
"$BUNDLE/bin/python" -m compileall -q "$BUNDLE"

if [ -f "$BUNDLE/bin/ansible-playbook" ] && [ ! -f "$BUNDLE/bin/ansible-playbook.py" ]; then
    mv "$BUNDLE/bin/ansible-playbook" "$BUNDLE/bin/ansible-playbook.py"
    cat > "$BUNDLE/bin/ansible-playbook" <<'EOF'
#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$SCRIPT_DIR/python" "$SCRIPT_DIR/ansible-playbook.py" "$@"
EOF
    chmod +x "$BUNDLE/bin/ansible-playbook"
fi

echo "Built bundled Ansible environment at $BUNDLE"
