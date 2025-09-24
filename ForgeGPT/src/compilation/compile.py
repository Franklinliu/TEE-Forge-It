import os
import subprocess

def xargo_compile_sgx_project(work_dir, project_name):
	"""
	使用 .bashrc 中的 docker-sgx-xargo-build 脚本编译 forked_repo 下的 SGX 库项目。
	:param project_name: forked_repo 下的子目录名（即 SGX 库项目名）
	"""
	# 调用 bash -i -c 保证加载 .bashrc 并执行函数
	cmd = f"bash -i -c 'docker-sgx-xargo-build {project_name} {os.path.basename(work_dir)}'"
	process = subprocess.Popen(cmd, shell=True, cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
	output_lines = []
	for line in process.stdout:
		print(line, end='')  # 实时输出
		output_lines.append(line)
	process.stdout.close()
	process.wait()
	output = ''.join(output_lines)
	# 检查常见 Rust 编译错误关键字
	error_keywords = [
		'error:', 'panicked at', "thread 'main' panicked", 'failed to compile', 'could not compile', 'aborting due to', 'error[E', 'error: could not', "error: process didn't exit successfully"
	]
	if any(keyword in output for keyword in error_keywords):
		print("编译失败：", output)
		raise RuntimeError(output)
	print("编译成功：", output)
	return output

def cargo_compile_sgx_project(work_dir, project_name):
	"""
	使用 .bashrc 中的 docker-sgx-cargo-build 脚本编译 forked_repo 下的 SGX 库项目。
	:param project_name: forked_repo 下的子目录名（即 SGX 库项目名）
	"""
	# 调用 bash -i -c 保证加载 .bashrc 并执行函数
	cmd = f"bash -i -c 'docker-sgx-cargo-build {project_name} {os.path.basename(work_dir)}'"
	process = subprocess.Popen(cmd, shell=True, cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
	output_lines = []
	for line in process.stdout:
		print(line, end='')  # 实时输出
		output_lines.append(line)
	process.stdout.close()
	process.wait()
	output = ''.join(output_lines)
	# 检查常见 Rust 编译错误关键字
	error_keywords = [
     	'failed to parse',
		'error:', 'panicked at', "thread 'main' panicked", 'failed to compile', 'could not compile', 'aborting due to', 'error[E', 'error: could not', "error: process didn't exit successfully"
	]
	if any(keyword in output for keyword in error_keywords):
		print("编译失败：", output)
		raise RuntimeError(output)
	print("编译成功：", output)
	return output

# 示例用法：
# xargo_compile_sgx_project("sgx-world", 'regex-sgx')
