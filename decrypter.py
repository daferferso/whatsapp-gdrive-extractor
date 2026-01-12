import os
import json
import glob
import re
import base64
import hmac
import math
from hashlib import sha256
try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES

def encryptionloop(*, first_iteration_data: bytes, privateseed: bytes = b'\x00' * 32, message: bytes, outputBytes: int):
    # The private key and the seed are used to create the HMAC key
    privatekey = hmac.new(privateseed, msg=first_iteration_data, digestmod=sha256).digest()

    data = b''
    output = b''
    numPermutations = int(math.ceil(float(outputBytes) / float(32)))
    i = 1
    while i < numPermutations + 1:
        hasher = hmac.new(privatekey, msg=data, digestmod=sha256)
        if message is not None:
            hasher.update(message)
        hasher.update(i.to_bytes(1, byteorder='big'))
        data = hasher.digest()
        bytestowrite = min(outputBytes, len(data))
        output += data[:bytestowrite]
        i += 1
    return output

def get_metadata_keys(root_key):
    enc_key = encryptionloop(
        first_iteration_data=root_key,
        message=b'metadata encryption',
        outputBytes=32)
    auth_key = encryptionloop(
        first_iteration_data=root_key,
        message=b'metadata authentication',
        outputBytes=32)
    return enc_key, auth_key

def get_media_keys(root_key):
    enc_key = encryptionloop(
        first_iteration_data=root_key,
        message=b'media encryption',
        outputBytes=32)
    auth_key = encryptionloop(
        first_iteration_data=root_key,
        message=b'media authentication',
        outputBytes=32)
    return enc_key, auth_key

def decrypt_data(data, enc_key, auth_key, is_metadata=False):
    try:
        if is_metadata:
            # Base64 decoding for metadata
            encoded = base64.b64decode(data)
        else:
            encoded = data
        
        pos = 0
        if len(encoded) < 1 + 16 + 1 + 32:
            return None

        iv_len = encoded[pos]
        pos += 1
        if iv_len != 16:
             # print(f"IV Size is not 16, got {iv_len}")
             return None

        iv = encoded[pos:pos+16]
        pos += 16
        
        mac_len = encoded[pos]
        pos += 1
        if mac_len != 32:
            # print(f"MAC Size is not 32, got {mac_len}")
            return None

        mac = encoded[pos:pos+32]
        pos += 32
        
        encrypted_content = encoded[pos:]
        
        # Authentication
        hmac_auth = hmac.new(auth_key, digestmod='sha256')
        hmac_auth.update(iv)
        hmac_auth.update(encrypted_content)
        computed_mac = hmac_auth.digest()
        
        if computed_mac != mac:
            # print("MAC does not match")
            pass # proceed?

        # Decryption
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted_bytes = cipher.decrypt(encrypted_content)
        
        # Unpad
        pad_len = decrypted_bytes[-1]
        if pad_len < 1 or pad_len > 16:
             pass
        else:
            decrypted_bytes = decrypted_bytes[:-pad_len]
            
        return decrypted_bytes
    except Exception as e:
        # print(f"Decryption failed: {e}")
        return None

def sanitize_filename(name):

    unsafe_chars = ['\\', '/', '*', '?', ':', '"', '<', '>', '|']

    for char in unsafe_chars:

        name = name.replace(char, '_')

    return name

def process_backup(backup_dir, output_dir, key_file):
    if not os.path.exists(key_file):
        print(f"Key file {key_file} not found.")
        return

    with open(key_file, "rb") as kf:
        root_key = kf.read()
    
    # Handle hex encoded key file if necessary
    if len(root_key) == 64:
        try:
            # Check if it looks like hex
            root_key.decode('utf-8')
            # It might be hex
            root_key = bytes.fromhex(root_key.decode('utf-8'))
        except:
            pass # assume binary
    
    meta_enc_key, meta_auth_key = get_metadata_keys(root_key)
    media_enc_key, media_auth_key = get_media_keys(root_key)
    
    os.makedirs(output_dir, exist_ok=True)
    
    count = 0
    for root, dirs, files in os.walk(backup_dir):
        for file in files:
            if file.endswith(".mcrypt1"):
                mcrypt_path = os.path.join(root, file)
                metadata_path = mcrypt_path + "-metadata"
                
                # Decrypt content
                try:
                    with open(mcrypt_path, 'rb') as f:
                        content = f.read()
                    
                    decrypted_content = decrypt_data(content, media_enc_key, media_auth_key)
                    
                    if decrypted_content:
                        # Determine filename
                        final_name = os.path.basename(mcrypt_path) # Fallback
                        
                        if os.path.exists(metadata_path):
                            with open(metadata_path, 'r') as f:
                                meta_content = f.read().strip()
                            
                            decrypted_meta = decrypt_data(meta_content, meta_enc_key, meta_auth_key, is_metadata=True)
                            if decrypted_meta:
                                try:
                                    meta_json = json.loads(decrypted_meta.decode('utf-8'))
                                    if 'name' in meta_json:
                                        final_name = sanitize_filename(meta_json['name'])
                                except:
                                    pass
                        
                        # Save
                        output_path = os.path.join(output_dir, final_name)
                        if not os.path.exists(output_path):
                            with open(output_path, 'wb') as f:
                                f.write(decrypted_content)
                            print(f"Restored: {final_name}")
                            count += 1
                        else:
                            # print(f"Skipped existing: {final_name}")
                            pass
                    else:
                        print(f"Failed to decrypt content: {file}")
                except Exception as e:
                    print(f"Error processing {file}: {e}")

    print(f"Decrypted and restored {count} files to {output_dir}")
