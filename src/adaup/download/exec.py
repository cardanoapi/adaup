#!/usr/bin/env python

import subprocess
import sys
import os

def executor(cmd, show_command=True, throw_error=False, stream_output=False):
    """
    Execute a command using subprocess and handle options.

    Args:
        cmd (list): Command to execute as a list of strings.
        show_command (bool): Whether to print the executed command. Default is True.
        throw_error (bool): Whether to raise an exception if command fails. Default is False.
        stream_output (bool): Whether to stream output directly to stdout/stderr instead of capturing it. Default is False.

    Returns:
        The return code of the command execution.

    Raises:
        subprocess.CalledProcessError: If the command returns a non-zero exit code and throw_error=True.
    """
    try:
        # Print the command before executing it
        if show_command:
            print(f"Executing: {' '.join(cmd)}")

        # Execute the command using subprocess.run
        if stream_output:
            # Stream output directly to stdout/stderr
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line-buffered
            )

            # Function to read and print lines from a stream as they arrive
            def read_stream(stream, prefix):
                for line in iter(stream.readline, ''):
                    if line.strip():  # Only print non-empty lines
                        print(f"{prefix}: {line}", end='')

            # Read stdout and stderr streams concurrently
            import threading
            stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, 'STDOUT'))
            stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, 'STDERR'))

            stdout_thread.start()
            stderr_thread.start()

            # Wait for process to complete
            return_code = process.wait()

            # Ensure all output is flushed before exiting
            stdout_thread.join()
            stderr_thread.join()

        else:
            # Original behavior: capture and print after execution
            result = subprocess.run(cmd, capture_output=True, text=True)

            # Print all output regardless of error status
            if result.stdout:
                print(f"STDOUT: {result.stdout}")
            if result.stderr:
                print(f"STDERR: {result.stderr}")
        if not stream_output:
            # Check for errors and handle accordingly
            if 'process' in locals() and process.returncode != 0:
                error_msg = f"Command failed with exit code {process.returncode}: {' '.join(cmd)}"
                print(f"Error: {error_msg}")
                if throw_error:
                    raise subprocess.CalledProcessError(process.returncode, cmd)
            elif 'result' in locals() and result.returncode != 0:
                error_msg = f"Command failed with exit code {result.returncode}: {' '.join(cmd)}"
                print(f"Error: {error_msg}")
                if throw_error:
                    raise subprocess.CalledProcessError(result.returncode, cmd)

        # Return the appropriate return code
        return process.returncode if 'process' in locals() else result.returncode

    except Exception as e:
        if not stream_output:
            error_msg = f"Exception occurred while executing command: {e}"
            print(error_msg)
            if throw_error:
                raise

def exec(cmd, env=None):
    """
    Replace the current process with a new one, similar to Bash's exec.

    Args:
        cmd (list): Command and arguments as a list of strings.
        env (dict, optional): Environment variables for the new process. Defaults to None.

    Note: This function does not return; it replaces the current process.
    """
    if len(cmd) == 0:
        raise ValueError("Command cannot be empty")

    program = cmd[0]
    args = cmd

    # Use os.execvp or os.execvpe based on whether env is provided
    if env is None:
        os.execvp(program, args)
    else:
        # Make sure we have a copy of the environment
        env_copy = os.environ.copy()
        env_copy.update(env)
        os.execvpe(program, args, env_copy)
