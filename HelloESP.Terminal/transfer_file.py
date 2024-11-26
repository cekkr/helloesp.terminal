import time
import os
from typing import Optional, Tuple, List
import serial
import hashlib


class SerialCommandError(Exception):
    """Custom exception for serial command errors"""
    pass


class FileValidationError(Exception):
    """Custom exception for file validation errors"""
    pass


MAX_FILENAME_LENGTH = 255
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def validate_filename(filename: str) -> None:
    """
    Validate filename before sending to device.

    Args:
        filename: Name of file to validate

    Raises:
        FileValidationError: If filename is invalid
    """
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        raise FileValidationError(f"Filename too long (max {MAX_FILENAME_LENGTH} chars)")

    invalid_chars = set('\\/:*?"<>|')
    if any(c in invalid_chars for c in filename):
        raise FileValidationError("Filename contains invalid characters")

    if filename.startswith('.') or filename.startswith(' '):
        raise FileValidationError("Filename cannot start with dot or space")


def wait_for_response(ser: serial.Serial, timeout: float = 2.0) -> Tuple[bool, str]:
    """
    Wait for and parse response from device.

    Args:
        ser: Serial connection object
        timeout: Maximum time to wait for response in seconds

    Returns:
        Tuple of (success, message)
    """
    start_time = time.time()
    response = ""

    while (time.time() - start_time) < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8').strip()
            if line.startswith("OK:"):
                return True, line[3:].strip()
            elif line.startswith("ERROR:"):
                return False, line[6:].strip()
        time.sleep(0.1)

    raise SerialCommandError("Timeout waiting for response")


def write_file(ser: serial.Serial, filename: str, data: bytes) -> Tuple[bool, str]:
    """
    Write data to a file on the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to write
        data: Binary data to write to the file

    Returns:
        Tuple of (success, message)
    """
    try:
        # Validate filename and file size
        validate_filename(filename)

        if len(data) > MAX_FILE_SIZE:
            raise FileValidationError(f"File too large (max {MAX_FILE_SIZE} bytes)")

        if len(data) == 0:
            raise FileValidationError("Cannot write empty file")

        # Calculate file hash for verification
        file_hash = hashlib.md5(data).hexdigest()

        # First check if file exists
        command = f"$$$CHECK_FILE$$${filename}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        success, message = wait_for_response(ser)
        if success:
            # File exists, parse size
            try:
                existing_size = int(message)
                if existing_size == len(data):
                    return False, f"File exists with same size ({existing_size} bytes)"
            except ValueError:
                pass

        # Send write command with filename, size and hash
        command = f"$$$WRITE_FILE$$${filename},{len(data)},{file_hash}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        # Wait for ready signal
        success, message = wait_for_response(ser)
        if not success:
            return False, message

        # Send file data in chunks
        chunk_size = 1024
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            ser.write(chunk)
            ser.flush()

            # Optional: wait for chunk acknowledgment
            success, message = wait_for_response(ser)
            if not success:
                return False, f"Error writing chunk: {message}"

        # Wait for final verification
        return wait_for_response(ser)

    except (serial.SerialException, FileValidationError) as e:
        raise SerialCommandError(str(e))
    except Exception as e:
        raise SerialCommandError(f"Error writing file: {str(e)}")


def read_file(ser: serial.Serial, filename: str) -> bytes:
    """
    Read a file from the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to read

    Returns:
        File contents as bytes
    """
    try:
        validate_filename(filename)

        command = f"$$$READ_FILE$$${filename}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        # First response should contain file size and hash
        success, info = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Failed to get file info: {info}")

        try:
            size_str, expected_hash = info.split(',')
            file_size = int(size_str)
        except ValueError:
            raise SerialCommandError(f"Invalid file info received: {info}")

        if file_size > MAX_FILE_SIZE:
            raise SerialCommandError(f"File too large ({file_size} bytes)")

        # Read the file data in chunks
        data = bytearray()
        chunk_size = 1024

        while len(data) < file_size:
            chunk = ser.read(min(chunk_size, file_size - len(data)))
            if not chunk:
                raise SerialCommandError("Timeout reading file data")
            data.extend(chunk)

            # Send chunk acknowledgment
            ser.write(b"OK\n")
            ser.flush()

        # Verify file hash
        received_hash = hashlib.md5(data).hexdigest()
        if received_hash != expected_hash:
            raise SerialCommandError("File hash mismatch")

        # Wait for final OK
        success, message = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Error after reading file: {message}")

        return bytes(data)

    except (serial.SerialException, FileValidationError) as e:
        raise SerialCommandError(str(e))
    except Exception as e:
        raise SerialCommandError(f"Error reading file: {str(e)}")


def list_files(ser: serial.Serial) -> List[Tuple[str, int]]:
    """
    Get list of files and their sizes on the device.

    Args:
        ser: Serial connection object

    Returns:
        List of tuples containing (filename, size)
    """
    try:
        command = "$$$LIST_FILES$$$\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        success, files_str = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Failed to list files: {files_str}")

        # Parse filename,size pairs
        files = []
        for entry in files_str.split(';'):
            if entry:
                try:
                    fname, size_str = entry.split(',')
                    files.append((fname, int(size_str)))
                except ValueError:
                    raise SerialCommandError(f"Invalid file entry format: {entry}")

        return files

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error listing files: {str(e)}")


def delete_file(ser: serial.Serial, filename: str) -> Tuple[bool, str]:
    """
    Delete a file from the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to delete

    Returns:
        Tuple of (success, message)
    """
    try:
        validate_filename(filename)

        command = f"$$$DELETE_FILE$$${filename}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        return wait_for_response(ser)

    except (serial.SerialException, FileValidationError) as e:
        raise SerialCommandError(str(e))
    except Exception as e:
        raise SerialCommandError(f"Error deleting file: {str(e)}")


# Example usage:
if __name__ == "__main__":
    # Example of how to use the functions
    try:
        # Open serial connection
        ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

        # List existing files
        files = list_files(ser)
        print("Files on device:")
        for fname, size in files:
            print(f"  {fname}: {size} bytes")

        # Write a file
        with open('test.txt', 'rb') as f:
            data = f.read()
            success, msg = write_file(ser, 'test.txt', data)
            print(f"Write file: {msg}")

        # Read the file back
        data = read_file(ser, 'test.txt')
        print(f"Read {len(data)} bytes")

        # Delete the file
        success, msg = delete_file(ser, 'test.txt')
        print(f"Delete file: {msg}")

    except SerialCommandError as e:
        print(f"Command error: {str(e)}")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        ser.close()