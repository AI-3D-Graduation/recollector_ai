"""
360도 이미지 3D 뷰어 - 직접 실행 버전
Streamlit 없이 바로 Open3D 뷰어를 실행합니다.

사용법:
    python 360view_direct.py
    python 360view_direct.py --ply image360.ply
    python 360view_direct.py --ply image360.ply --points 200000 --size 5.0
"""

import argparse
import numpy as np
import open3d as o3d
import trimesh
from pathlib import Path


# ============================================================================
# 🎛️ 빠른 설정 (코드에서 직접 수정 가능)
# ============================================================================
# 명령줄 인자 없이 실행할 때 사용되는 기본값입니다.
# True/False로 간단히 변경하여 동작을 제어할 수 있습니다.

QUICK_SETTINGS = {
    # 파일 설정
    'ply_file': 'image360_2.ply',           # PLY 파일 경로
    
    # 시각화 설정
    'max_points': 3000000,                # 표시할 최대 포인트 수
    'point_size': 10.0,                   # 포인트 크기
    'fov': 100,                           # 시야각 (도)
    'bgcolor': 'black',                   # 배경색 (black/white/gray/darkgray)
    
    # 카메라 설정
    'camera_distance': 0.0,               # 초기 카메라 거리
    
    # 동작 설정
    'invert_points': True,                # True: 내부 시점, False: 외부 시점
    'show_axis': True,                    # 좌표축 표시 여부
    'horizontal_only': False,             # True: 가로 회전만, False: 자유 회전
    
    # 창 설정
    'window_width': 1400,                 # 창 너비
    'window_height': 900,                 # 창 높이
}

# ============================================================================


def load_ply(ply_path):
    """PLY 파일 로드"""
    if not Path(ply_path).exists():
        raise FileNotFoundError(f"PLY 파일을 찾을 수 없습니다: {ply_path}")
    
    mesh = trimesh.load(str(ply_path), process=False)
    pts = np.asarray(mesh.vertices)
    cols = None
    
    if hasattr(mesh, "visual") and hasattr(mesh.visual, "vertex_colors"):
        vc = np.asarray(mesh.visual.vertex_colors)
        cols = vc[:, :3] / 255.0
    
    print(f"✅ PLY 로드 완료: {len(pts):,}개 포인트")
    return pts, cols


def downsample(pts, cols, max_points):
    """포인트 다운샘플링"""
    if len(pts) > max_points:
        print(f"🔽 다운샘플링: {len(pts):,} → {max_points:,} 포인트")
        idx = np.random.choice(len(pts), max_points, replace=False)
        pts = pts[idx]
        cols = cols[idx] if cols is not None else None
    return pts, cols


def show_open3d_viewer(pts, cols, args):
    """Open3D 3D 뷰어 실행 (360도 내부 시점)"""
    
    print("\n" + "="*60)
    print("📊 포인트클라우드 정보")
    print("="*60)
    
    # 바운딩 박스 정보
    bbox_min = pts.min(axis=0)
    bbox_max = pts.max(axis=0)
    bbox_center = (bbox_min + bbox_max) / 2.0
    bbox_size = bbox_max - bbox_min
    
    print(f"포인트 수: {len(pts):,}개")
    print(f"바운딩 박스 중심: [{bbox_center[0]:.3f}, {bbox_center[1]:.3f}, {bbox_center[2]:.3f}]")
    print(f"바운딩 박스 크기: [{bbox_size[0]:.3f}, {bbox_size[1]:.3f}, {bbox_size[2]:.3f}]")
    print("="*60 + "\n")
    
    # 포인트 반전 (내부 시점)
    if args.invert:
        pts = -pts
        print("🔄 포인트 반전: 내부 시점으로 전환")
    
    # 포인트클라우드 생성
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    
    if cols is not None:
        pcd.colors = o3d.utility.Vector3dVector(cols)
        print("🎨 컬러 정보 적용")
    
    # Visualizer 생성
    print(f"\n🚀 Open3D 뷰어 시작...")
    print(f"   - FOV: {args.fov}°")
    print(f"   - 포인트 크기: {args.size}")
    print(f"   - 배경색: {args.bgcolor}")
    print(f"   - 초기 거리: {args.distance}")
    if args.horizontal_only:
        print(f"   - 회전 제한: 가로(수평) 회전만 가능")
    
    vis = o3d.visualization.Visualizer()
    vis.create_window(
        window_name="UniK3D 360° Viewer - Inside View",
        width=args.width,
        height=args.height
    )
    vis.add_geometry(pcd)
    
    # 렌더링 옵션
    opt = vis.get_render_option()
    
    # 배경색 설정
    bgcolor_map = {
        "black": (0.0, 0.0, 0.0),
        "white": (1.0, 1.0, 1.0),
        "gray": (0.5, 0.5, 0.5),
        "darkgray": (0.2, 0.2, 0.2)
    }
    opt.background_color = np.array(bgcolor_map.get(args.bgcolor, (0.0, 0.0, 0.0)), dtype=np.float32)
    opt.point_size = float(args.size)
    opt.show_coordinate_frame = args.axis
    
    # 중요: 포인트가 모든 각도에서 보이도록 설정
    opt.point_show_normal = False  # 법선 기반 렌더링 끄기
    
    # 카메라 설정
    ctr = vis.get_view_control()
    
    # 초기 렌더링
    vis.poll_events()
    vis.update_renderer()
    
    # 카메라 파라미터 설정
    params = ctr.convert_to_pinhole_camera_parameters()
    
    # Extrinsic 행렬 (카메라를 정확히 원점에 배치)
    camera_position = np.array([0.0, 0.0, args.distance])
    
    # 항등 회전 행렬 (회전 없음)
    R = np.eye(3, dtype=np.float64)
    
    # Extrinsic = [R | t] 여기서 t = -R @ camera_position
    extrinsic = np.eye(4, dtype=np.float64)
    extrinsic[:3, :3] = R
    extrinsic[:3, 3] = -R @ camera_position
    
    params.extrinsic = extrinsic
    
    # Intrinsic 행렬 (FOV 설정)
    intrinsic = params.intrinsic
    intrinsic.width = args.width
    intrinsic.height = args.height
    focal_length = intrinsic.width / (2.0 * np.tan(np.radians(args.fov / 2.0)))
    intrinsic.set_intrinsics(
        intrinsic.width,
        intrinsic.height,
        focal_length,
        focal_length,
        intrinsic.width / 2.0,
        intrinsic.height / 2.0
    )
    params.intrinsic = intrinsic
    
    # 카메라 파라미터 적용
    ctr.convert_from_pinhole_camera_parameters(params, allow_arbitrary=True)
    
    # 가로 회전만 가능하도록 제한 (옵션)
    if args.horizontal_only:
        # 초기 카메라 상태 저장
        initial_params = ctr.convert_to_pinhole_camera_parameters()
        initial_y = initial_params.extrinsic[1, 3]  # Y 위치 저장
        
        def lock_vertical_rotation(vis):
            """수직 회전을 잠그고 수평 회전만 허용"""
            ctr = vis.get_view_control()
            params = ctr.convert_to_pinhole_camera_parameters()
            
            # Y축 위치를 초기값으로 고정 (높이 변화 방지)
            extrinsic = params.extrinsic.copy()
            extrinsic[1, 3] = initial_y
            
            # Y축 회전 성분 제한 (pitch 제한)
            # extrinsic의 회전 행렬에서 Y축 회전을 0으로 유지
            R = extrinsic[:3, :3]
            
            # Y축 방향 벡터 추출
            up = R[:, 1]
            # Y축이 위를 향하도록 강제 (0, 1, 0에 가깝게)
            up[0] = 0.0  # X 성분 제거
            up[2] = 0.0  # Z 성분 제거
            up[1] = -1.0 if up[1] < 0 else 1.0  # Y 방향 유지
            
            # 정규화된 Y축으로 회전 행렬 재구성
            R[:, 1] = up / np.linalg.norm(up)
            
            # Z축(전방)과 X축(우측)을 재계산하여 직교성 유지
            forward = R[:, 2]
            forward[1] = 0.0  # Y 성분 제거 (수평 유지)
            forward = forward / (np.linalg.norm(forward) + 1e-10)
            R[:, 2] = forward
            
            right = np.cross(up, forward)
            right = right / (np.linalg.norm(right) + 1e-10)
            R[:, 0] = right
            
            extrinsic[:3, :3] = R
            params.extrinsic = extrinsic
            
            ctr.convert_from_pinhole_camera_parameters(params, allow_arbitrary=True)
            return False
        
        # 콜백 등록
        vis.register_animation_callback(lock_vertical_rotation)
    
    # 조작법 안내
    print("\n" + "="*60)
    print("🎮 조작법")
    print("="*60)
    if args.horizontal_only:
        print("  마우스 왼쪽 드래그: 좌우 회전만 가능 (수평 360°)")
        print("  ⚠️  위아래 회전 잠김")
    else:
        print("  마우스 왼쪽 드래그: 시점 회전 (주변 둘러보기)")
    print("  마우스 휠: 줌 인/아웃")
    print("  Shift + 마우스 드래그: 카메라 이동")
    print("  Ctrl + 마우스 드래그: 카메라 회전")
    print("  Q 또는 ESC: 종료")
    print("="*60 + "\n")
    
    # 뷰어 실행
    vis.run()
    vis.destroy_window()
    print("\n✅ 뷰어 종료")


def main():
    parser = argparse.ArgumentParser(
        description="360도 이미지 3D 뷰어 - 직접 실행 버전",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  python 360view_direct.py
  python 360view_direct.py --ply image360.ply
  python 360view_direct.py --ply image360.ply --points 200000 --size 7.0
  python 360view_direct.py --ply image360.ply --fov 100 --no-invert
  python 360view_direct.py --horizontal-only  # 가로 회전만
        """
    )
    
    # 파일 경로
    parser.add_argument(
        "--ply", 
        type=str, 
        default=QUICK_SETTINGS['ply_file'],
        help=f"PLY 파일 경로 (기본값: {QUICK_SETTINGS['ply_file']})"
    )
    
    # 포인트 설정
    parser.add_argument(
        "--points",
        type=int,
        default=QUICK_SETTINGS['max_points'],
        help=f"표시할 최대 포인트 수 (기본값: {QUICK_SETTINGS['max_points']})"
    )
    
    parser.add_argument(
        "--size",
        type=float,
        default=QUICK_SETTINGS['point_size'],
        help=f"포인트 크기 (기본값: {QUICK_SETTINGS['point_size']})"
    )
    
    # 카메라 설정
    parser.add_argument(
        "--fov",
        type=int,
        default=QUICK_SETTINGS['fov'],
        help=f"시야각 (FOV) in degrees (기본값: {QUICK_SETTINGS['fov']})"
    )
    
    parser.add_argument(
        "--distance",
        type=float,
        default=QUICK_SETTINGS['camera_distance'],
        help=f"카메라 초기 거리 (기본값: {QUICK_SETTINGS['camera_distance']})"
    )
    
    # 시각화 옵션
    parser.add_argument(
        "--bgcolor",
        type=str,
        default=QUICK_SETTINGS['bgcolor'],
        choices=["black", "white", "gray", "darkgray"],
        help=f"배경색 (기본값: {QUICK_SETTINGS['bgcolor']})"
    )
    
    parser.add_argument(
        "--width",
        type=int,
        default=QUICK_SETTINGS['window_width'],
        help=f"창 너비 (기본값: {QUICK_SETTINGS['window_width']})"
    )
    
    parser.add_argument(
        "--height",
        type=int,
        default=QUICK_SETTINGS['window_height'],
        help=f"창 높이 (기본값: {QUICK_SETTINGS['window_height']})"
    )
    
    parser.add_argument(
        "--no-invert",
        dest="invert",
        action="store_false",
        help="포인트 반전 안 함 (외부 시점)"
    )
    
    parser.add_argument(
        "--no-normals",
        dest="normals",
        action="store_false",
        help="법선 추정 안 함"
    )
    
    parser.add_argument(
        "--no-axis",
        dest="axis",
        action="store_false",
        help="좌표축 숨기기"
    )
    
    parser.add_argument(
        "--horizontal-only",
        dest="horizontal_only",
        action="store_true",
        help="가로(수평) 회전만 허용 (위아래 회전 잠김)"
    )
    
    # 기본값 설정
    parser.set_defaults(
        invert=QUICK_SETTINGS['invert_points'],
        normals=True,
        axis=QUICK_SETTINGS['show_axis'],
        horizontal_only=QUICK_SETTINGS['horizontal_only']
    )
    
    args = parser.parse_args()
    
    # 실행
    print("\n" + "="*60)
    print("🌀 UniK3D 360° Viewer - Direct Mode")
    print("="*60)
    print(f"PLY 파일: {args.ply}\n")
    
    try:
        # PLY 로드
        pts, cols = load_ply(args.ply)
        
        # 다운샘플링
        pts, cols = downsample(pts, cols, args.points)
        
        # 뷰어 실행
        show_open3d_viewer(pts, cols, args)
        
    except FileNotFoundError as e:
        print(f"\n❌ 오류: {e}")
        print(f"💡 현재 디렉토리: {Path.cwd()}")
        print(f"💡 사용 가능한 PLY 파일을 --ply 옵션으로 지정하세요.\n")
        return 1
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
