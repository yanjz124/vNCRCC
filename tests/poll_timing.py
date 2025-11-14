import time
import httpx

API = 'http://127.0.0.1:8000/api/v1'

def measure_once():
    with httpx.Client(timeout=10) as c:
        t0 = time.time()
        r1 = c.get(API + '/aircraft/latest')
        t1 = time.time()
        r2 = c.get(API + '/p56/')
        t2 = time.time()
        r3 = c.get(API + '/frz/')
        t3 = time.time()
        r4 = c.get(API + '/sfra/')
        t4 = time.time()

    print('aircraft/latest: status', r1.status_code, 'dt', round((t1-t0)*1000), 'ms')
    print('p56: status', r2.status_code, 'dt after aircraft', round((t2-t1)*1000), 'ms')
    print('frz: status', r3.status_code, 'dt after aircraft', round((t3-t1)*1000), 'ms')
    print('sfra: status', r4.status_code, 'dt after aircraft', round((t4-t1)*1000), 'ms')
    try:
        snap = r1.json()
        print('snapshot fetched_at:', snap.get('fetched_at'))
    except Exception:
        pass

if __name__ == '__main__':
    for i in range(5):
        print('\nRun', i+1)
        measure_once()
        time.sleep(3)
