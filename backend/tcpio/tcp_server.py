# backend/tcpio/tcp_server.py

import traceback
import socket
import threading
from backend.tcpio.protocol import TCPProtocol
from backend.main_controller.main_controller import MainController
import time


class TCPServer:
    def __init__(self, host="0.0.0.0", port=8000, app_controller=None):
        self.host = host
        self.port = port
        self.clients = {}         # addr → socket
        self.truck_sockets = {}   # truck_id → socket
        self.running = False

        # MainController 초기화 및 트럭 소켓 맵 설정
        self.app = app_controller if app_controller else MainController(port_map={})
        
        # MainController에 tcp_server 참조 설정 (순환 참조 방지를 위해 명시적으로 설정)
        if hasattr(self.app, 'set_tcp_server'):
            self.app.set_tcp_server(self)
        else:
            setattr(self.app, 'tcp_server', self)
            print("[✅ TCP 서버 참조 설정] MainController에 tcp_server 참조가 설정되었습니다.")
        
        self.app.set_truck_commander(self.truck_sockets)

    @staticmethod
    def is_port_in_use(port, host='0.0.0.0'):
        """주어진 포트가 이미 사용 중인지 확인합니다.
        
        Args:
            port (int): 확인할 포트 번호
            host (str): 확인할 호스트 주소
            
        Returns:
            bool: 포트가 사용 중이면 True, 아니면 False
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return False  # 바인딩 성공 - 포트가 사용 가능
            except OSError:
                return True   # 바인딩 실패 - 포트가 이미 사용 중
    
    @staticmethod
    def find_available_port(start_port=8001, max_port=8100, host='0.0.0.0'):
        """지정된 범위 내에서 사용 가능한 첫 번째 포트를 찾습니다.
        
        Args:
            start_port (int): 검색 시작 포트
            max_port (int): 검색 종료 포트
            host (str): 확인할 호스트 주소
            
        Returns:
            int: 사용 가능한 포트 번호, 없으면 None
        """
        for port in range(start_port, max_port + 1):
            if not TCPServer.is_port_in_use(port, host):
                return port
        return None

    def start(self):
        self.running = True
        
        try:
            # 새 소켓 생성
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # SO_REUSEADDR 및 SO_REUSEPORT 옵션 설정 (가능한 경우)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                # SO_REUSEPORT는 일부 플랫폼에서만 지원
                self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                # 지원하지 않는 플랫폼에서는 무시
                pass
            
            # 소켓 타임아웃 설정
            self.server_sock.settimeout(1.0)  # 1초 타임아웃으로 accept 대기
            
            # 바인딩 시도
            try:
                self.server_sock.bind((self.host, self.port))
            except OSError as e:
                if "Address already in use" in str(e):
                    print(f"[⚠️ 포트 {self.port} 사용 중] 5초 후 다시 시도...")
                    # 기존 소켓 닫기
                    self.server_sock.close()
                    # 5초 대기
                    time.sleep(5)
                    # 새 소켓 생성 및 재시도
                    self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except (AttributeError, OSError):
                        pass
                    self.server_sock.settimeout(1.0)
                    self.server_sock.bind((self.host, self.port))
                else:
                    raise
                
            self.server_sock.listen(5)  # 백로그 크기 명시적 설정
            print(f"[🚀 TCP 서버 시작] {self.host}:{self.port}")

            # 클라이언트 연결을 위한 루프
            while self.running:
                try:
                    client_sock, addr = self.server_sock.accept()
                    # 클라이언트 연결 타임아웃 설정
                    client_sock.settimeout(30.0)  # 클라이언트 소켓에 30초 타임아웃 설정
                    self.clients[addr] = client_sock
                    print(f"[✅ 클라이언트 연결됨] {addr}")

                    threading.Thread(
                        target=self.handle_client,
                        args=(client_sock, addr),
                        daemon=True
                    ).start()
                except socket.timeout:
                    # accept 타임아웃은 정상 - running 플래그 확인하고 계속
                    continue
                except OSError as e:
                    # 소켓이 닫혔거나 다른 소켓 오류 발생
                    if self.running:  # 정상 종료가 아닌 경우에만 오류 로깅
                        print(f"[⚠️ TCP 서버 소켓 오류] {e}")
                    break

        except Exception as e:
            print(f"[⚠️ TCP 서버 오류] {e}")
            print(traceback.format_exc())
        finally:
            self.stop()

    def handle_client(self, client_sock, addr):
        """클라이언트 연결 처리 메서드"""
        try:
            temp_truck_id = f"TEMP_{addr[1]}"
            self.truck_sockets[temp_truck_id] = client_sock
            
            # 예외 처리 추가 - 안전하게 처리
            try:
                self.app.set_truck_commander(self.truck_sockets)
            except Exception as e:
                print(f"[⚠️ 명령 전송자 설정 오류] {e}")
                print("[🔄 오류 복구] 명령 전송자 설정 오류를 무시하고 계속 진행합니다.")
                # 스택 추적 출력
                import traceback
                traceback.print_exc()

            # 소켓 설정 개선
            try:
                # TCP Keepalive 설정
                client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # 플랫폼 따라 TCP Keepalive 세부 설정 (리눅스)
                import platform
                if platform.system() == "Linux":
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)  # 60초 비활성 후 keepalive 시작
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # 10초마다 keepalive 패킷 전송
                    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)     # 5번 실패하면 연결 끊김
            except (ImportError, AttributeError) as e:
                print(f"[ℹ️ 정보] TCP Keepalive 세부 설정이 지원되지 않습니다: {e}")
            
            # 소켓 타임아웃 설정 (클라이언트 응답 타임아웃)
            client_sock.settimeout(120.0)  # 2분 타임아웃

            last_activity_time = time.time()
            
            while True:
                try:
                    current_time = time.time()
                    # 장시간 연결 유지 확인 (5분 이상 활동 없을 때)
                    if current_time - last_activity_time > 300:  # 5분
                        print(f"[ℹ️ 활동 확인] {addr} - 장시간 활동이 없는 연결 확인 중")
                        # 소켓이 살아있는지 확인
                        try:
                            # 0바이트 데이터로 소켓 상태 확인
                            client_sock.send(b'')
                            last_activity_time = current_time
                            print(f"[✅ 연결 유지] {addr} - 연결 상태 양호")
                        except:
                            print(f"[⚠️ 연결 끊김] {addr} - 장시간 활동이 없는 연결 종료")
                            break
                    
                    # 헤더 데이터 수신 (4바이트)
                    header_data = client_sock.recv(4)
                    if not header_data:
                        print(f"[❌ 연결 종료] {addr}")
                        break
                        
                    if len(header_data) < 4:
                        print(f"[⚠️ 불완전한 헤더 수신] {addr}")
                        continue
                    
                    # 활동 시간 갱신
                    last_activity_time = current_time
                    
                    # 페이로드 길이 추출
                    payload_len = header_data[3]
                    
                    # 페이로드 수신 (있는 경우)
                    payload_data = b''
                    if payload_len > 0:
                        payload_data = client_sock.recv(payload_len)
                        if len(payload_data) < payload_len:
                            print(f"[⚠️ 불완전한 페이로드 수신] {addr}")
                            continue
                    
                    # 전체 메시지
                    raw_data = header_data + payload_data
                    print(f"[📩 수신 원문] {raw_data.hex()}")
                    
                    # 메시지 파싱 - 예외 처리 추가
                    try:
                        message = TCPProtocol.parse_message(raw_data)
                        if "type" in message and message["type"] == "INVALID":
                            print(f"[⚠️ 메시지 파싱 실패] {message.get('error', '알 수 없는 오류')}")
                            continue
                    except Exception as e:
                        print(f"[⚠️ 메시지 파싱 오류] {e}, 데이터: {raw_data.hex()}")
                        continue  # 연결은 유지
                    
                    # ✅ 여기에서 무조건 truck_id 등록
                    truck_id = message.get("sender")
                    if truck_id:
                        if truck_id not in self.truck_sockets:
                            print(f"[🔗 등록] 트럭 '{truck_id}' 소켓 등록")
                            # ✅ 임시 트럭 ID 제거
                            if temp_truck_id in self.truck_sockets:
                                del self.truck_sockets[temp_truck_id]
                        self.truck_sockets[truck_id] = client_sock
                        
                        # ✅ AppController의 TruckCommandSender 업데이트 - 예외 처리 추가
                        try:
                            self.app.set_truck_commander(self.truck_sockets)
                        except Exception as e:
                            print(f"[⚠️ 명령 전송자 설정 오류] {e}")
                            # 오류는 무시하고 진행

                    # 하트비트 메시지 특별 처리
                    if message.get("cmd") == "HELLO":
                        print(f"[💓 하트비트] 트럭 {truck_id}에서 하트비트 수신")
                        # 하트비트 응답 메시지 전송
                        try:
                            response = TCPProtocol.build_message(
                                sender="SERVER",
                                receiver=truck_id,
                                cmd="HEARTBEAT_ACK",
                                payload={}
                            )
                            client_sock.sendall(response)
                        except Exception as e:
                            print(f"[⚠️ 하트비트 응답 오류] {e}")
                        continue

                    # ✅ 메시지 처리 위임 - 예외 처리 추가
                    try:
                        self.app.handle_message(message)
                    except Exception as e:
                        print(f"[⚠️ 메시지 처리 오류] {e}")
                        import traceback
                        traceback.print_exc()
                        # 처리 오류가 발생해도 연결은 유지

                except ConnectionResetError:
                    print(f"[⚠️ 연결 재설정] {addr}")
                    break
                except ConnectionAbortedError:
                    print(f"[⚠️ 연결 중단] {addr}")
                    break
                except socket.timeout:
                    # 2분간 데이터 없으면 하트비트 체크 메시지 전송
                    print(f"[⚠️ 소켓 타임아웃] {addr} - 하트비트 체크 시도")
                    try:
                        # 클라이언트가 등록된 트럭인지 확인
                        registered_truck_id = None
                        for tid, sock in self.truck_sockets.items():
                            if sock == client_sock and not tid.startswith("TEMP_"):
                                registered_truck_id = tid
                                break
                        
                        if registered_truck_id:
                            # 하트비트 요청 메시지 전송
                            heartbeat_msg = TCPProtocol.build_message(
                                sender="SERVER",
                                receiver=registered_truck_id,
                                cmd="HEARTBEAT_CHECK", 
                                payload={}
                            )
                            client_sock.sendall(heartbeat_msg)
                            print(f"[💓 하트비트 체크] {registered_truck_id}에게 생존 확인 메시지 전송")
                            # 활동 시간 갱신
                            last_activity_time = time.time()
                        else:
                            print(f"[⚠️ 미등록 연결] {addr} - 타임아웃으로 종료")
                            break
                    except:
                        print(f"[❌ 연결 종료] {addr} - 하트비트 체크 실패")
                        break
                except Exception as e:
                    print(f"[⚠️ 에러] {addr} → {e}")
                    import traceback
                    traceback.print_exc()
                    # 치명적이지 않은 오류는 무시하고 계속 진행 (연결 유지)
                    continue  # 연결을 유지하기 위해 continue 사용

        finally:
            # 여기서 클라이언트 소켓을 닫고 정리합니다
            try:
                # 클라이언트 소켓 닫기
                client_sock.close()
                
                # 트럭 매핑에서 제거
                for truck_id, sock in list(self.truck_sockets.items()):
                    if sock == client_sock:
                        del self.truck_sockets[truck_id]
                        print(f"[🔌 트럭 연결 종료] {truck_id}")
                
                # 클라이언트 딕셔너리에서 제거
                if addr in self.clients:
                    del self.clients[addr]
                    
                # AppController의 TruckCommandSender 업데이트 - 예외 처리 추가
                try:
                    self.app.set_truck_commander(self.truck_sockets)
                except Exception as e:
                    print(f"[⚠️ 명령 전송자 설정 오류 (정리 중)] {e}")
            except Exception as e:
                print(f"[⚠️ 소켓 정리 오류] {addr} → {e}")

    def safe_stop(self):
        """서버 소켓 및 모든 클라이언트 연결만 종료 (리소스 유지)"""
        # 먼저 running 플래그를 False로 설정
        old_running = self.running
        self.running = False
        
        if not old_running:
            # 이미 중지된 경우 중복 실행 방지
            return
        
        print("[🛑 TCP 서버 안전 종료 시작]")
        
        # 모든 클라이언트 소켓 정리
        for addr, sock in list(self.clients.items()):
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
                print(f"[🔌 클라이언트 연결 종료] {addr}")
            except Exception as e:
                print(f"[⚠️ 클라이언트 소켓 닫기 오류] {addr} → {e}")
        
        # 서버 소켓 닫기
        try:
            if hasattr(self, 'server_sock'):
                try:
                    self.server_sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass  # shutdown이 실패해도 close는 진행
                self.server_sock.close()
                print("[🔌 서버 소켓 종료됨]")
        except Exception as e:
            print(f"[⚠️ 서버 소켓 닫기 오류] {e}")
        
        # 연결 정보 초기화 (참조는 유지)
        self.clients.clear()
        self.truck_sockets.clear()
        
        print("[🔌 TCP 서버 안전 종료됨 (리소스는 유지됨)]")

    def stop(self):
        """서버 소켓 및 모든 클라이언트 연결 종료 + 리소스 정리
        
        주의: 이 메서드는 전체 리소스를 정리하므로 재시작 시에는 safe_stop을 사용해야 함
        """
        # 이미 종료된 경우 처리
        if not self.running and not hasattr(self, 'server_sock'):
            return
            
        # 먼저 안전하게 소켓 종료
        self.safe_stop()
        
        # 여기서부터는 전체 리소스 정리 과정
        # MainController 등의 리소스는 건드리지 않음
        print("[🛑 TCP 서버 완전 종료됨]")

    def send_message(self, client_id, cmd, payload=None):
        """지정된 클라이언트에 메시지 전송"""
        if payload is None:
            payload = {}
            
        # 메시지 로깅
        if cmd != "HEARTBEAT_ACK":  # 하트비트는 로깅에서 제외
            print(f"[📤 송신] {client_id} ← {cmd} | payload={payload}")
        
        # 클라이언트 존재 확인
        if client_id not in self.clients:
            print(f"[❌ 전송 오류] 클라이언트 {client_id}가 연결되어 있지 않습니다.")
            return False
            
        client_sock = self.clients[client_id]["socket"]
        
        # 바이너리 메시지 생성
        message = TCPProtocol.build_message(
            sender="SERVER",
            receiver=client_id,
            cmd=cmd,
            payload=payload
        )
        
        try:
            client_sock.sendall(message)
            return True
        except Exception as e:
            print(f"[❌ 전송 오류] {client_id} - {e}")
            self._close_client(client_id)  # 오류 발생한 클라이언트 연결 종료
            return False 