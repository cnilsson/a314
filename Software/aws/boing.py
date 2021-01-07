import math
import pygame


class BoingBall(object):
    W = 640
    H = 512
    w = 120
    h = 57

    BLACK = (0, 0, 0)
    GRAY = (102, 102, 102)
    LIGHTGRAY = (170, 170, 170)
    WHITE = (255, 255, 255)
    RED = (255, 26, 1)
    PURPLE = (183, 45, 168)

    def __init__(self, surface):
        self.surface = surface
        self.phase = 0.0
        self.dp = 1.3
        self.x = self.tx(170)
        self.dx = self.tx(0.8)
        self.right = True
        self.y_ang = 0.0

    def tx(self, x):
        return (x - self.W / 2) * (self.w / self.W) + (self.w / 2)

    def ty(self, y):
        return (y - self.H / 2) * (self.h / self.H) + (self.h / 2)

    @staticmethod
    def get_lat(phase, i):
        if i == 0:
            return -90.0
        elif i == 9:
            return 90.0
        else:
            return -90.0 + phase + (i-1) * 22.5

    @classmethod
    def calc_points(cls, phase):
        points = {}
        sin_lat = {}
        for i in range(10):
            points[i] = {}
            lat = cls.get_lat(phase, i)
            sin_lat[i] = math.sin(lat * math.pi / 180.0)

        for j in range(9):
            lon = -90.0 + j * 22.5
            y = math.sin(lon * math.pi / 180.0)
            l = math.cos(lon * math.pi / 180.0)
            for i in range(10):
                x = sin_lat[i] * l
                points[i][j] = (x, y)

        return points

    @staticmethod
    def tilt_sphere(points, ang):
        st = math.sin(ang * math.pi / 180.0)
        ct = math.cos(ang * math.pi / 180.0)
        for i in points:
            for j in points[i]:
                x, y = points[i][j]
                x, y = x * ct - y * st, x * st + y * ct
                points[i][j] = x, y

    @staticmethod
    def scale_and_translate(points, sx, sy, tx, ty):
        for i in points:
            for j in points[i]:
                x, y = points[i][j]
                x, y = x * sx + tx, y * sy + ty
                points[i][j] = x, y

    @classmethod
    def transform(cls, points, sx, sy, tx, ty):
        cls.tilt_sphere(points, 17.0)
        cls.scale_and_translate(points, sx, sy, tx, ty)

    def draw_meridians(self, screen, points):
        for i in range(10):
            for j in range(8):
                p1 = points[i][j]
                p2 = points[i][j+1]
                pygame.draw.line(screen, self.BLACK, p1, p2)

    def draw_parabels(self, screen, points):
        for i in range(7):
            p1 = points[0][i+1]
            p2 = points[9][i+1]
            pygame.draw.line(screen, self.BLACK, p1, p2)

    def fill_tiles(self, screen, points, alter):
        for j in range(8):
            for i in range(9):
                p1 = points[i][j]
                p2 = points[i+1][j]
                p3 = points[i+1][j+1]
                p4 = points[i][j+1]
                pygame.draw.polygon(screen, self.RED if alter else self.WHITE, (p1, p2, p3, p4))
                alter = not alter

    def draw_shadow(self, screen, points, offset):
        ps = []
        for i in range(9):
            x, y = points[0][i]
            ps.append((x + offset, y))
        for i in range(8):
            x, y = points[9][7-i]
            ps.append((x + offset, y))
        pygame.draw.polygon(screen, self.GRAY, ps)

    def draw_wireframe(self, screen):
        for i in range(13):
            p1 = (50, i*36)
            p2 = (590, i*36)
            pygame.draw.line(screen, self.PURPLE, p1, p2, 2)

        for i in range(16):
            p1 = (50 + i*36, 0)
            p2 = (50 + i*36, 432)
            pygame.draw.line(screen, self.PURPLE, p1, p2, 2)

        for i in range(16):
            p1 = (50 + i*36, 432)
            p2 = (i*42.666, 480)
            pygame.draw.line(screen, self.PURPLE, p1, p2, 2)

        ys = [442, 454, 468]
        for i in range(3):
            y = ys[i]
            x1 = 50 - 50.0*(y-432)/(480.0-432.0)
            p1 = (x1, y)
            p2 = (640-x1, y)
            pygame.draw.line(screen, self.PURPLE, p1, p2, 2)

    def calc_and_draw(self, screen, phase, scale, x, y):
        points = self.calc_points(phase % 22.5)
        self.transform(points, scale, scale / 2, x, y)
        self.draw_shadow(screen, points, 8)
        #self.draw_wireframe(screen)
        self.fill_tiles(screen, points, phase >= 22.5)
        self.draw_meridians(screen, points)
        self.draw_parabels(screen, points)

    def update(self):
        self.phase = (self.phase + ((45.0 - self.dp) if self.right else self.dp)) % 45.0
        self.x += self.dx if self.right else -self.dx
        if self.x >= self.tx(500):
            self.right = False
        elif self.x <= self.tx(140):
            self.right = True
        self.y_ang = (self.y_ang + 2.4) % 360.0
        self.y = self.ty(390.0) - self.ty(220.0) * math.fabs(math.cos(self.y_ang * math.pi / 180.0))

        self.calc_and_draw(self.surface, self.phase, 120.0 * self.w / self.W, self.x, self.y)
