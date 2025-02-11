import hashlib


## utils to hash and verify passwords
## will be used in checking passwords during login, etc.


def hash_password(password: str) -> str:
   """
   Returns a salted SHA256 hash of the given password
   """
  
   hashed_pw = hashlib.sha256(password.encode('utf-8'))
   return hashed_pw.hexdigest()
  


def verify_password(password: str, stored_hash: str) -> bool:
   """
   Verifies the given password against the stored hash
   """
  
   try:
       return hash_password(password) == stored_hash
   except:
       print("System Error while verifying password.")
       return False
  

