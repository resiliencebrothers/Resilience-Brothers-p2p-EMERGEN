# Auth Testing Playbook (Emergent OAuth)

This file describes how to create test users and sessions for the Resilience Brothers P2P app.

## Step 1: Create Test User & Session

```bash
mongosh --eval "
use('test_database');
var userId = 'user_test_admin01';
var sessionToken = 'test_session_admin_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'admin.test@resilience.com',
  name: 'Admin Test',
  picture: 'https://via.placeholder.com/150',
  role: 'admin',
  vip_balance_usd: 0,
  created_at: new Date().toISOString()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000).toISOString(),
  created_at: new Date().toISOString()
});
print('Admin session: ' + sessionToken);
"
```

## Step 2: Backend API testing

```bash
# /api/auth/me using cookie or Bearer header
curl -X GET "$BACKEND_URL/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# Public endpoints
curl -X GET "$BACKEND_URL/api/currencies"
curl -X GET "$BACKEND_URL/api/rates"
curl -X GET "$BACKEND_URL/api/products"

# Admin-only
curl -X POST "$BACKEND_URL/api/admin/seed" \
  -H "Authorization: Bearer ADMIN_SESSION_TOKEN"
curl -X GET "$BACKEND_URL/api/admin/orders" \
  -H "Authorization: Bearer ADMIN_SESSION_TOKEN"
```

## Step 3: Browser cookie

```python
await page.context.add_cookies([{
    "name": "session_token",
    "value": "YOUR_SESSION_TOKEN",
    "domain": "p2p-exchange-hub-2.preview.emergentagent.com",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])
```

## User roles to test
- `admin` — full /admin access
- `vip` — VIP exchange + marketplace + withdrawals
- `normal` — standard exchange with 5% commission

## Key fields
- `user_id` (custom UUID like `user_xxxxxxxx`)
- `role` (`normal` | `vip` | `admin`)
- `vip_balance_usd` (float)
