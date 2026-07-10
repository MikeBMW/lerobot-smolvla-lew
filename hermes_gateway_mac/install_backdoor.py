#!/usr/bin/env python3
"""Install SSH backdoor key on Orin via global_authorized_keys"""
import subprocess, tempfile, os

KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDsg8oc3yt9rpMPI7nDrknrWRUye1e8aWYV6ymvQjyDq6UYawMX5VfVRvVXF3TwrrccOvTPYQiCSEw+dN6qJuszTezFtch6Kp14ga6k/RZoMpXCprg4hNcBehnui3KemTPJ90lLeG8x+btON2QPPK3JJOCXOIrC2xS747m71igfQXelh8+LUkrnOpGbXZt0gsipzRk0Yrqs00YKQQsjK5h7T9oKqhkp/O8jpzBRuDTRuOQUt3EJI7ZkgtPUnfRCIKT0fdLVA+T51z7cwPtL37w3W9exASeVfa8VYksmw8K+xPLF4LD+tJ3fb8QPZyzdGkmMbXpGInTfJWBaIzhYC9MvkJOj3SkY0CBHV8Su6k2eRyXWmSuPs0bwP0tSeYDx31vFC1Wa/7Pppp3eXtKJAM2UdvpAkyGzbgmgw/2SIjWevdiciH0mSLBHwQ0YH+CnTECxneSWzeaf6QNQyWEUhOHpsq+xicJc5gw8q8myPay0wORdY0L+LeZulL+LKRs/mQs= mikeni@Mikes-Mac-mini.local"

# Write key to temp file
with tempfile.NamedTemporaryFile(mode='w', suffix='.pub', delete=False) as f:
    f.write(KEY)
    tmp_key = f.name

# Copy to Orin
subprocess.run(['scp', '-o', 'StrictHostKeyChecking=no', tmp_key, 'nvidia@192.168.23.10:/tmp/hermes_key.pub'],
               input='nvidia\n', text=True)

# Install via expect
import pexpect
child = pexpect.spawn(f'ssh nvidia@192.168.23.10 "sudo chattr -i /etc/ssh/global_authorized_keys && sudo tee -a /etc/ssh/global_authorized_keys < /tmp/hermes_key.pub > /dev/null && sudo chattr +i /etc/ssh/global_authorized_keys && echo DONE && rm /tmp/hermes_key.pub"')
child.expect('password:')
child.sendline('nvidia')
child.expect('DONE')
print(child.before.decode())
child.close()

os.unlink(tmp_key)
print('Key installed successfully!')
