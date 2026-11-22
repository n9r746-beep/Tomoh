"""Password hashes and verification; plain passwords are never persisted."""
import hashlib
import hmac
import secrets

def save(repo, user_id, password):
    if len(password) < 12:
        raise ValueError('كلمة المرور لا تقل عن ١٢ حرفًا.')
    salt=secrets.token_hex(16)
    hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    repo.db.execute('INSERT INTO user_credentials(user_id,salt,password_hash) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET salt=excluded.salt,password_hash=excluded.password_hash',(user_id,salt,hashed))

def verify(repo, user_id, password):
    row=repo.db.fetch_one('SELECT salt,password_hash FROM user_credentials WHERE user_id=?',(user_id,))
    if not row:
        return False
    hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(row['salt']),600000).hex()
    return hmac.compare_digest(hashed,row['password_hash'])
