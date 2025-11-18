# Rate Limiting Deployment Guide

## Overview
Comprehensive rate limiting has been implemented at both the nginx and FastAPI levels to protect against spam and DDoS attacks.

## Changes Made

### 1. **nginx Rate Limiting** (nginx-vncrcc.conf)
- **API endpoints**: 6 requests/minute (1 every 10 seconds), burst of 3
- **Static files**: 30 requests/minute, burst of 10
- **Page loads**: 10 requests/minute, burst of 5
- **Localhost exemption**: Internal API calls from 127.0.0.1 are not rate-limited

### 2. **FastAPI Rate Limiting** (slowapi)
- Added `slowapi>=0.1.9` to requirements.txt
- All API v1 endpoints protected with `@limiter.limit("6/minute")`
- Localhost exemption in key function (127.0.0.1, ::1)
- Returns 429 status code when limit exceeded

### 3. **Protected Endpoints**
All endpoints now have rate limiting:
- `/api/v1/aircraft/*` (latest, list, history)
- `/api/v1/p56/*` (current, incidents, clear)
- `/api/v1/sfra/`, `/api/v1/frz/`, `/api/v1/vso/`
- `/api/v1/geo/`, `/api/v1/elevation/`, `/api/v1/incidents/`
- `/health` (exempt from rate limiting)

## Deployment Steps

### On Production Server (JY@JY1)

1. **Install slowapi**:
   ```bash
   cd /path/to/vNCRCC
   source venv/bin/activate  # if using virtualenv
   pip install slowapi
   ```

2. **Update nginx configuration**:
   ```bash
   sudo cp nginx-vncrcc.conf /etc/nginx/sites-available/vncrcc.conf
   sudo nginx -t  # test configuration
   sudo systemctl reload nginx
   ```

3. **Restart the service**:
   ```bash
   sudo systemctl restart vncrcc.service
   ```

4. **Verify rate limiting is working**:
   ```bash
   # Test API rate limit (should get 429 after 6 requests in 1 minute)
   for i in {1..10}; do curl -I http://localhost/api/v1/aircraft/list; sleep 5; done
   
   # Check nginx logs for rate limit blocks
   sudo tail -f /var/log/nginx/error.log | grep "limiting requests"
   ```

## Configuration Tuning

### To adjust rate limits in nginx:
Edit `nginx-vncrcc.conf` and modify the `rate=` values:
- `6r/m` = 6 requests per minute (1 every 10 seconds)
- `30r/m` = 30 requests per minute (2 per second)
- `burst=N` = allow N extra requests before rejecting

### To adjust rate limits in FastAPI:
Edit `src/vncrcc/rate_limit.py` and change:
- `default_limits=["6/minute"]` to desired rate
- Or modify individual endpoint decorators: `@limiter.limit("10/minute")`

## Testing

### Test from external IP:
```bash
# Should get rate limited after 6 requests
for i in {1..10}; do
  curl -I https://vncrcc.org/api/v1/aircraft/list
  sleep 5
done
```

### Test localhost exemption:
```bash
# Should NOT get rate limited (unlimited from localhost)
ssh JY@JY1
for i in {1..20}; do
  curl -I http://127.0.0.1:8000/api/v1/aircraft/list
done
```

## Monitoring

### Check rate limit hits:
```bash
# nginx access log
sudo tail -f /var/log/nginx/access.log | grep " 429 "

# nginx error log
sudo tail -f /var/log/nginx/error.log | grep "limiting"

# Application logs (if using systemd)
sudo journalctl -u vncrcc.service -f | grep "RateLimitExceeded"
```

## Troubleshooting

### If legitimate users are getting rate limited:
1. Increase the rate in nginx: `rate=12r/m` (2 per 10 seconds)
2. Increase burst size: `burst=5` or `burst=10`
3. Check if frontend polling interval is too aggressive (currently 15 seconds)

### If internal API calls are being blocked:
- Verify nginx is forwarding `X-Forwarded-For` header
- Check that `get_rate_limit_key()` in `rate_limit.py` properly exempts localhost
- Ensure nginx `geo $limit` block correctly identifies 127.0.0.1

## Security Notes
- Rate limits are per-IP address
- Localhost (127.0.0.1, ::1) is fully exempted at both nginx and FastAPI levels
- 429 responses include `Retry-After` header when using slowapi
- Nginx applies limits before traffic reaches FastAPI (more efficient)
