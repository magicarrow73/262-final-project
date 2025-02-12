import hashlib


## utils to hash and verify passwords
## will be used in checking passwords during login, etc.


def hash_password(password: str) -> str:
   """
   Returns a SHA256 hash of the given password
   """
  
   hashed_pw = hashlib.sha256(password.encode('utf-8'))
   return hashed_pw.hexdigest()
  


def verify_password(hashed_password: str, stored_hash: str) -> bool:
   """
   Verifies the given hashed_password against the stored hash
   """
  
   try:
       return hashed_password == stored_hash
   except:
       print("System Error while verifying password.")
       return False
  

