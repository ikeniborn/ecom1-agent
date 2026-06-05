def run(vm, params):
    basket_id = params['basket_id']
    identity = vm.exec(path='/bin/id', args=[])
    sql1 = "SELECT basket_id, record_path, customer_id, store_id, basket_status FROM shopping_baskets WHERE basket_id = '" + basket_id + "'"
    basket_row = vm.exec(path='/bin/sql', args=[], stdin=sql1)
    payments_help = vm.exec(path='/bin/payments', args=['--help'])
    sql2 = "SELECT line_number, product_sku, requested_quantity FROM shopping_basket_items WHERE basket_id = '" + basket_id + "' ORDER BY line_number"
    basket_items = vm.exec(path='/bin/sql', args=[], stdin=sql2)

    basket_path = ''
    customer_id = ''
    store_id = ''
    basket_status = ''
    stdout1 = getattr(basket_row, 'stdout', '') or ''
    lines = [l for l in stdout1.splitlines() if l.strip()]
    if len(lines) >= 2:
        header = [c.strip() for c in lines[0].split(',')]
        row = [c.strip() for c in lines[1].split(',')]
        rec = dict(zip(header, row))
        basket_path = rec.get('record_path', '')
        customer_id = rec.get('customer_id', '')
        store_id = rec.get('store_id', '')
        basket_status = rec.get('basket_status', '')

    checkout_policy = vm.read(path='/docs/checkout.md', number=True)

    checkout_result = vm.exec(path='/bin/payments', args=['checkout', 'submit', '--basket', basket_id])
    out = getattr(checkout_result, 'stdout', '') or ''
    err = getattr(checkout_result, 'stderr', '') or ''
    exit_code = getattr(checkout_result, 'exit_code', 0)

    payment_path = ''
    for line in out.splitlines():
        s = line.strip()
        if 'payment_path' in s or s.startswith('/records/payments') or '/payments/' in s:
            for tok in s.replace(',', ' ').replace('=', ' ').replace(':', ' ').split():
                if tok.startswith('/') and 'payment' in tok:
                    payment_path = tok
                    break
            if payment_path:
                break

    # agents_md scope: payments supports payment workflow state + refund approval/finalization.
    # 'checkout submit' not enumerated -> r012 downgrade.
    outcome = 'OUTCOME_NONE_UNSUPPORTED'

    refs = []
    if basket_path:
        refs.append(basket_path)
    if payment_path:
        refs.append(payment_path)
    refs.append('/docs/checkout.md')

    summary = (out or err).strip().replace('\n', ' ')[:200]
    message = 'Checkout submitted for ' + basket_id + '. Result: ' + summary
    vm.answer(message=message, outcome=outcome, refs=refs)
    return {'outcome': outcome, 'refs': refs}
